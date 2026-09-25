"""册（Repo）管理：一库 = 一 memory.db + 一 graph.json（协议 v1.29）。

- 书库 = 文件夹：managed 册落 `<数据根>/repos/<group_key>/<repo_id>/`，
  展示名不入路径（group_key 独立生成）；
- 登记表 `repos/index.json` 持久化受管开关与活动库，原子写，坏索引不覆盖原件；
- 现行全局三件套绑定为默认库（external 指向现行配置路径，legacy 零移动迁移）；
- 册间完全隔离：各自线层/图层/FTS/管线，不跨册建边；只在检索结果层融合。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import SearchResponse, SearchResult

logger = logging.getLogger(__name__)

DEFAULT_REPO_ID = "rp_default"
INDEX_VERSION = 1
JOINT_RRF_K = 60  # 册间等权 RRF 常数（与 rrf_k 语义一致，独立取值不随配置漂移）


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _group_key(group: str) -> str:
    """书库安全目录键：由归一化展示名确定性导出，同名书库共享一个文件夹。"""
    digest = hashlib.blake2s(group.strip().casefold().encode("utf-8"), digest_size=4).hexdigest()
    return f"grp-{digest}"


@dataclass
class RepoRecord:
    repo_id: str
    name: str
    note: str = ""
    group: str | None = None
    group_key: str | None = None
    root_kind: str = "external"  # external（登记既有路径）| managed（repos/ 下新建）
    db_path: str = ""
    json_path: str = ""
    managed: bool = True
    created_at: str = ""
    updated_at: str = ""


class RepoEntry:
    """运行中的册：登记记录 + 已打开的三件套。"""

    def __init__(self, record: RepoRecord, db: Database, es: EventStore, gs: GraphStore):
        self.record = record
        self.db = db
        self.event_store = es
        self.graph_store = gs

    @property
    def repo_id(self) -> str:
        return self.record.repo_id

    @property
    def name(self) -> str:
        return self.record.name


class RepoManager:
    """库登记与生命周期。所有写操作在事件循环内串行执行（单 worker 纪律不变）。"""

    def __init__(self) -> None:
        self.records: dict[str, RepoRecord] = {}
        self.entries: dict[str, RepoEntry] = {}  # 已打开的册
        self.active_id: str = DEFAULT_REPO_ID

    # ── 路径 ──

    @property
    def repos_root(self) -> Path:
        return Path(settings.memory_db_path).parent / "repos"

    @property
    def index_path(self) -> Path:
        return self.repos_root / "index.json"

    # ── 默认库绑定（legacy 兼容：现行三件套 = 默认库，零移动迁移）──

    def bind_default(self, db: Database, es: EventStore, gs: GraphStore) -> RepoRecord:
        record = RepoRecord(
            repo_id=DEFAULT_REPO_ID,
            name="默认库",
            root_kind="external",
            db_path=str(Path(settings.memory_db_path).resolve()),
            json_path=str(Path(settings.graph_json_path).resolve()),
            managed=True,
            created_at=_now(),
            updated_at=_now(),
        )
        self.records[DEFAULT_REPO_ID] = record
        self.entries[DEFAULT_REPO_ID] = RepoEntry(record, db, es, gs)
        self.active_id = DEFAULT_REPO_ID
        return record

    # ── 登记表 ──

    async def initialize(self) -> None:
        """读登记表 → 缺失则落盘（默认库登记即 legacy 迁移）→ 打开其它受管库。

        坏索引：保留原件、以默认库启动，不阻断基础对话。
        """
        self.repos_root.mkdir(parents=True, exist_ok=True)
        if self.index_path.exists():
            try:
                self._load_index()
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                logger.error("repos/index.json 解析失败，保留原件、仅以默认库启动: %s", exc)
                return
        else:
            self._save_index()
            logger.info("库登记表初始化完成（默认库 external 登记于 %s）", self.index_path)
        # 默认库路径以现行配置为真源（env/dpim.json 变更后跟随）
        self.records[DEFAULT_REPO_ID].db_path = str(Path(settings.memory_db_path).resolve())
        self.records[DEFAULT_REPO_ID].json_path = str(Path(settings.graph_json_path).resolve())
        for record in list(self.records.values()):
            if record.repo_id == DEFAULT_REPO_ID or not record.managed:
                continue
            try:
                await self._open(record)
            except Exception as exc:
                logger.error(
                    "册 %s(%s) 加载失败，跳过（登记保留）: %s", record.name, record.repo_id, exc
                )

    def _load_index(self) -> None:
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        records = {}
        for row in data.get("repos", []):
            record = RepoRecord(
                repo_id=row["repo_id"], name=row.get("name", ""),
                note=row.get("note", ""), group=row.get("group"),
                group_key=row.get("group_key"), root_kind=row.get("root_kind", "external"),
                db_path=row.get("db_path", ""), json_path=row.get("json_path", ""),
                managed=bool(row.get("managed", True)),
                created_at=row.get("created_at", ""), updated_at=row.get("updated_at", ""),
            )
            records[record.repo_id] = record
        if DEFAULT_REPO_ID not in records:
            records[DEFAULT_REPO_ID] = self.records[DEFAULT_REPO_ID]
        self.records = records
        active = data.get("active_repo_id", DEFAULT_REPO_ID)
        self.active_id = active if active in records else DEFAULT_REPO_ID

    def _save_index(self) -> None:
        """原子写登记表（tmp + os.replace）；损坏原件不被空表覆盖由调用方保证。"""
        self.repos_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "active_repo_id": self.active_id,
            "repos": [asdict(r) for r in self.records.values()],
        }
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=self.repos_root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.index_path)
        except Exception:
            os.unlink(tmp)
            raise

    # ── 解析 ──

    def resolve(self, repo_id: str | None = None) -> RepoEntry | None:
        """解析已加载的册：repo_id 空 = 活动库；未知或未加载返回 None。"""
        target = repo_id or self.active_id
        return self.entries.get(target)

    def require(self, repo_id: str | None = None) -> RepoEntry:
        entry = self.resolve(repo_id)
        if entry is None:
            raise KeyError(repo_id or self.active_id)
        return entry

    def managed_entries(self) -> list[RepoEntry]:
        """受管且已加载的册，默认库在最前（登记序稳定）。"""
        return [self.entries[r.repo_id] for r in self.records.values() if r.repo_id in self.entries]

    # ── 生命周期 ──

    async def _open(self, record: RepoRecord) -> RepoEntry:
        if record.repo_id in self.entries:
            return self.entries[record.repo_id]
        db = Database(record.db_path)
        await db.connect()
        es = EventStore(db)
        await es.rebuild_fts()
        gs = GraphStore(db, json_path=record.json_path)
        await gs.load()
        if not Path(record.json_path).exists():
            await gs.save()  # 新库落一份空图：「一库 = 一 db + 一 json」即日成立
        await gs.reconcile(es)
        if gs.dirty:
            await gs.flush()
        entry = RepoEntry(record, db, es, gs)
        self.entries[record.repo_id] = entry
        logger.info("库已打开：%s(%s)", record.name, record.repo_id)
        return entry

    async def _close(self, repo_id: str) -> None:
        entry = self.entries.pop(repo_id, None)
        if entry is None:
            return
        try:
            if entry.graph_store.dirty:
                await entry.graph_store.save()
            await entry.db.close()
        except Exception as exc:
            logger.error("册 %s 关闭异常（登记保留）: %s", repo_id, exc)
        logger.info("库已关闭：%s", repo_id)

    async def close(self) -> None:
        """关闭全部非默认库（默认库由 api lifespan 统一关闭）。"""
        for repo_id in list(self.entries):
            if repo_id != DEFAULT_REPO_ID:
                await self._close(repo_id)

    # ── 管理操作（api 层调用，写后 refresh_key 由 api 负责）──

    async def create_repo(
        self, name: str, note: str = "", group: str = "",
        root_kind: str = "managed", root: str = "",
    ) -> RepoRecord:
        """建库。managed 落书库根；external 只登记用户目录（须含两文件，禁设清单校验）。"""
        repo_id = f"rp-{uuid.uuid4().hex[:12]}"
        if root_kind == "external":
            db_path, json_path = self._validate_external_root(root)
            group_key = None
        else:
            group_key = _group_key(group) if group.strip() else None
            repo_dir = self.repos_root / repo_id
            if group_key:
                repo_dir = self.repos_root / group_key / repo_id
            repo_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(repo_dir / "memory.db")
            json_path = str(repo_dir / "graph.json")
        record = RepoRecord(
            repo_id=repo_id,
            name=name, note=note,
            group=group.strip() or None, group_key=group_key,
            root_kind=root_kind, db_path=db_path, json_path=json_path,
            managed=True, created_at=_now(), updated_at=_now(),
        )
        self.records[record.repo_id] = record
        self._save_index()
        await self._open(record)
        return record

    def _validate_external_root(self, root: str) -> tuple[str, str]:
        """external root 校验：真实目录 + 两文件齐备 + 禁设清单 + 重复登记拒绝。"""
        resolved = Path(root).resolve()
        if not root.strip():
            raise ValueError("external 册必须提供目录路径")
        if not resolved.is_dir():
            raise ValueError(f"目录不存在：{root}")
        home = Path.home().resolve()
        forbidden = [
            resolved.parent == resolved,                     # 磁盘根
            resolved == home,                                # 用户主目录
            resolved == self.repos_root.parent.resolve(),    # 数据根自身
            resolved == self.repos_root.resolve(),           # repos 根
        ]
        if any(forbidden):
            raise ValueError("该路径在禁设清单内（磁盘根 / 主目录 / 数据根 / repos 根）")
        db_path = resolved / "memory.db"
        json_path = resolved / "graph.json"
        if not db_path.is_file() or not json_path.is_file():
            raise ValueError("目录中须同时存在 memory.db 与 graph.json 才可登记为册")
        for record in self.records.values():
            if {Path(record.db_path).resolve(), Path(record.json_path).resolve()} == {
                db_path, json_path
            }:
                raise ValueError(f"该路径已登记为册 {record.name}({record.repo_id})")
        return str(db_path), str(json_path)

    async def update_repo(
        self, repo_id: str, *, name: str | None = None, note: str | None = None,
        group: str | None = None, managed: bool | None = None,
    ) -> RepoRecord:
        record = self.records.get(repo_id)
        if record is None:
            raise KeyError(repo_id)
        changes: dict = {}
        if name is not None:
            changes["name"] = name
        if note is not None:
            changes["note"] = note
        if group is not None and record.root_kind == "managed":
            changes["group"] = group.strip() or None
            changes["group_key"] = _group_key(group) if group.strip() else None
        if managed is not None and managed != record.managed and repo_id != DEFAULT_REPO_ID:
            changes["managed"] = managed
        if not changes:
            return record
        record = replace(record, updated_at=_now(), **changes)
        self.records[repo_id] = record
        # 受管开关即时生效：开 = 打开三件套；关 = 落盘关闭（文件不动）
        if "managed" in changes:
            if changes["managed"]:
                await self._open(record)
            else:
                await self._close(repo_id)
                if self.active_id == repo_id:
                    self.active_id = DEFAULT_REPO_ID
        self._save_index()
        return record

    async def delete_repo(self, repo_id: str) -> None:
        """摘除登记（不删任何磁盘文件）；默认库与活动库不可摘。"""
        if repo_id == DEFAULT_REPO_ID:
            raise ValueError("默认库不可摘除")
        if self.active_id == repo_id:
            raise ValueError("活动库不可摘除，请先切换活动库")
        record = self.records.pop(repo_id, None)
        if record is None:
            raise KeyError(repo_id)
        await self._close(repo_id)
        self._save_index()

    async def activate(self, repo_id: str) -> None:
        record = self.records.get(repo_id)
        if record is None:
            raise KeyError(repo_id)
        if not record.managed:
            raise ValueError("未受管的册不能设为活动库")
        self.active_id = repo_id
        self._save_index()


def fuse_joint_results(per_repo: list[tuple[RepoEntry, SearchResponse]]) -> list[SearchResult]:
    """册间融合（v1.29 联合检索）：等权 RRF + 去重 + 来源锚定。

    去重键：事件 = content_hash（缺省退回 event_id）；节点 = (类型, 标题归一)。
    被合并项保留首命中负载，source_repos 列出全部来源库名。
    """
    merged: dict[tuple, dict] = {}
    for entry, resp in per_repo:
        for rank, hit in enumerate(resp.results, start=1):
            if hit.kind == "event":
                key = ("event", hit.content_hash or hit.node_id)
            else:
                key = ("node", hit.source_type, hit.title.strip().casefold())
            gain = 1.0 / (JOINT_RRF_K + rank)
            item = merged.get(key)
            if item is None:
                item = {
                    "hit": hit.model_copy(deep=True),
                    "score": 0.0,
                    "repos": [],
                }
                # 来源册锚定：首命中册写入 repo_id/repo_name
                item["hit"].repo_id = entry.repo_id
                item["hit"].repo_name = entry.name
                merged[key] = item
            item["score"] += gain
            if entry.name not in item["repos"]:
                item["repos"].append(entry.name)
    out: list[SearchResult] = []
    for item in merged.values():
        hit: SearchResult = item["hit"]
        hit.score = item["score"]
        hit.source_repos = item["repos"]
        out.append(hit)
    return out
