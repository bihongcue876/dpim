"""SQLite 连接 + WAL 模式 + FTS5 建表"""

from pathlib import Path

import aiosqlite

from core.config import settings


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
        """)
        await self.conn.commit()

    async def _migrate(self):
        """轻量迁移（按 user_version 递进）。

        v1 → v2：events 增 error 列（v1.28 失败原因落库）。
        只增列不重写，旧库无感升级；新库建表即含 error，此处仅对齐版本号。
        """
        cursor = await self.conn.execute("PRAGMA user_version")
        version = (await cursor.fetchone())[0]
        if version >= 2:
            return
        cursor = await self.conn.execute("PRAGMA table_info(events)")
        cols = {row[1] for row in await cursor.fetchall()}
        if cols and "error" not in cols:
            await self.conn.execute(
                "ALTER TABLE events ADD COLUMN error TEXT NOT NULL DEFAULT ''"
            )
        await self.conn.execute("PRAGMA user_version = 2")
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()
