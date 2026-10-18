"""SQLite 连接 + WAL 模式 + FTS5 建表"""

import logging
from pathlib import Path

import aiosqlite

from core.config import settings
from core.graph_ops import CREATE_SQL as GRAPH_OPS_DDL

logger = logging.getLogger(__name__)

# 当前 schema 版本（PRAGMA user_version）
# v1 初始 / v2 events.error / v3 graph_ops（图层操作日志）
SCHEMA_VERSION = 3


class Database:
    def __init__(self, db_path: str = settings.memory_db_path):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        # 跨进程并发：显式声明忙等待（此前依赖 Python sqlite3 默认 5s 的隐式值）
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self._create_tables()
        await self._migrate()

    async def _create_tables(self):
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                raw_content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                event_type TEXT NOT NULL
                    CHECK(event_type IN ('interaction','data','source')),
                status TEXT NOT NULL DEFAULT 'raw'
                    CHECK(status IN ('raw','indexed','linked','failed','skipped')),
                graph_refs TEXT DEFAULT '[]',
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(created_at);
            CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                event_id UNINDEXED,
                raw_content
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(
                node_id UNINDEXED,
                title,
                content
            );
        """ + GRAPH_OPS_DDL)
        await self.conn.commit()

    async def _migrate(self):
        """轻量迁移（按 user_version 递进）。

        v1 → v2：events 增 error 列（v1.28 失败原因落库）。
        v2 → v3：新增 graph_ops 表（图层操作日志：可重放、可审计）。
        只增列/增表不重写，旧库无感升级；新库建表即最新，此处仅对齐版本号。
        """
        cursor = await self.conn.execute("PRAGMA user_version")
        version = (await cursor.fetchone())[0]
        if version >= SCHEMA_VERSION:
            return
        if version < 2:
            cursor = await self.conn.execute("PRAGMA table_info(events)")
            cols = {row[1] for row in await cursor.fetchall()}
            if cols and "error" not in cols:
                await self.conn.execute(
                    "ALTER TABLE events ADD COLUMN error TEXT NOT NULL DEFAULT ''"
                )
        if version < 3:
            await self.conn.executescript(GRAPH_OPS_DDL)
        await self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    # ── 容量与 WAL 治理（P4）──

    async def db_size(self) -> int:
        """主库文件字节数（0 = 不可读/内存库）。"""
        try:
            return Path(self.db_path).stat().st_size
        except OSError:
            return 0

    async def wal_size(self) -> int:
        """WAL 文件字节数（0 = 无 WAL 文件）。"""
        try:
            return Path(f"{self.db_path}-wal").stat().st_size
        except OSError:
            return 0

    async def checkpoint(self, mode: str = "TRUNCATE") -> tuple[int, int, int]:
        """WAL 检查点（默认 TRUNCATE：收回到主库并截断 WAL 文件）。

        此前全仓没有任何 checkpoint → 长期运行 WAL 无界增长。
        返回 `(busy, log_frames, checkpointed_frames)`；失败只告警不阻断。
        """
        try:
            cursor = await self.conn.execute(f"PRAGMA wal_checkpoint({mode})")
            row = await cursor.fetchone()
            if row is None:
                return (0, 0, 0)
            return (int(row[0]), int(row[1]), int(row[2]))
        except Exception as exc:
            logger.warning("WAL checkpoint 失败（不影响运行）: %s", exc)
            return (0, 0, 0)
