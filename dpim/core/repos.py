"""库（Repo）与文件数据资源接口：一库 = 一 memory.db + 一 graph.json。

基层纪律（2026-10-03 加固，吸收言明通（YMT）项目的库存储经验，见 docs/数据资源接口设计20261003.md）：

- 登记表 `repos/index.json` 是「文件数据资源」的唯一真值来源：原子写 + 结构校验 +
  **坏索引只读锁存**（原件永不覆盖，写操作一律拒绝而非静默丢登记）；
- 展示名（库名/分组名）不参与路径构造：`group_key` 独立生成，同名分组复用既有键；
- 分组变更 = 目录迁移（managed，失败回滚）；external 库只改显示分组；
- external root 只登记引用：绝对路径 + 拒符号链接 + 禁设清单（含与数据根的双向包含）；
- 可用性诊断（文件是否就位/加载错误/上次 reconcile）不打开库文件即可给出；
- 库间完全隔离：各自线层/图层/FTS/管线，不跨库建边；只在检索结果层融合（`fuse_joint_results`）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from core.atomic import atomic_write_text
from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.lockfile import LockError, SingleInstanceLock
from core.maintenance import create_backup
from core.models import SearchResponse, SearchResult

logger = logging.getLogger(__name__)

DEFAULT_REPO_ID = "rp_default"
INDEX_VERSION = 1
# 重建登记表时排除的目录名：这些目录里出现的 memory.db/graph.json 是**副本/留档**，不是库
# （整库备份 `backups/<stamp>/memory.db` 尤其容易被误认成受管库）
NON_REPO_DIRNAMES = ("backups", "trash")
JOINT_RRF_K = 60  # 库间等权 RRF 常数（与 rrf_k 语义一致，独立取值不随配置漂移）
# 联合检索候选池（v1.30）：每库取候选数 = limit × 系数，下限 MIN；
# 上限受 SearchRequest.limit（≤100）约束。取候选池而非直接取最终页，是修「双重分页」的关键。
JOINT_CANDIDATE_FACTOR = 3
JOINT_MIN_CANDIDATES = 50

# 登记表护栏：条数与体量上限（防手编/异常膨胀拖垮启动）
MAX_REPOS = 100
MAX_INDEX_BYTES = 4 * 1024 * 1024
# 展示名长度（与 wire 模型保持一致）
MAX_NAME = 80
MAX_GROUP = 60
MAX_NOTE = 500

GROUP_KEY_PREFIX = "grp_"
_LEGACY_GROUP_KEY_PREFIX = "grp-"  # 旧实现：由展示名 blake2s 派生（仅识别用，不再生成）


class RepoIndexError(ValueError):
    """登记表不可写或结构非法：坏索引锁存，绝不静默覆盖原件。"""


class RepoConflictError(ValueError):
    """路径/书目冲突（该目录已登记为库等）：API 层映射 409。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _new_group_key() -> str:
    """书库目录键：独立生成（展示名不参与路径构造，防注入）。"""
    return f"{GROUP_KEY_PREFIX}{uuid.uuid4().hex[:10]}"


def _legacy_group_key(group: str) -> str:
    """旧实现的键算法（仅用于识别历史登记，不再用于生成新键）。"""
    digest = hashlib.blake2s(group.strip().casefold().encode("utf-8"), digest_size=4).hexdigest()
    return f"{_LEGACY_GROUP_KEY_PREFIX}{digest}"


def is_legacy_group_key(key: str | None) -> bool:
    return bool(key) and str(key).startswith(_LEGACY_GROUP_KEY_PREFIX)


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _inside(child: Path, parent: Path) -> bool:
    """child 是否等于 parent 或位于其子树内。"""
    return child == parent or parent in child.parents


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
    """运行中的库：登记记录 + 已打开的三件套 + 基层诊断态。"""

    def __init__(self, record: RepoRecord, db: Database, es: EventStore, gs: GraphStore):
        self.record = record
        self.db = db
        self.event_store = es
        self.graph_store = gs
        # 跨进程互斥：持有到本库关闭为止（OS 文件锁，进程退出自动释放）
        self.lock: SingleInstanceLock | None = None
        # 基层诊断（供 /repos 与前端健康位使用）
        self.load_error: str = ""
        self.last_reconcile_at: str = ""
        self.reconcile_changed: int = 0

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
        self.entries: dict[str, RepoEntry] = {}  # 已打开的库
        self.active_id: str = DEFAULT_REPO_ID
        # 坏索引锁存：载入失败后登记表只读，任何写操作拒绝覆盖原件
        self.index_error: str = ""
        self.index_writable: bool = True
        # 加载失败的库（登记保留，诊断可见）
        self.load_errors: dict[str, str] = {}

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
        # 跨进程互斥：默认库被占用时拒绝启动（否则两个进程整文件改写会互相覆盖）
        lock = SingleInstanceLock(record.db_path + ".lock")
        lock.acquire_or_raise(what="默认库")
        self.records[DEFAULT_REPO_ID] = record
        entry = RepoEntry(record, db, es, gs)
        entry.lock = lock
        self.entries[DEFAULT_REPO_ID] = entry
        self.active_id = DEFAULT_REPO_ID
        return record

    # ── 登记表 ──

    async def initialize(self) -> None:
        """读登记表 → 缺失则落盘（默认库登记即 legacy 迁移）→ 打开其它受管库。

        坏索引：**保留原件 + 只读锁存**（``index_error`` / ``index_writable``），
        仅以默认库启动，绝不覆盖原件、也不阻断基础功能。
        """
        self.repos_root.mkdir(parents=True, exist_ok=True)
        if self.index_path.exists():
            try:
                self._load_index()
            except RepoIndexError as exc:
                self.index_error = str(exc)
                self.index_writable = False
                logger.error(
                    "repos/index.json 不可用：%s（原件保留；登记表锁存只读，"
                    "建库/改库/摘库将被拒绝）", exc,
                )
                return
            except Exception as exc:  # 兜底：任何未预期错误同样锁存，绝不覆盖
                self.index_error = f"登记表读取失败：{type(exc).__name__}: {exc}"
                self.index_writable = False
                logger.exception("repos/index.json 读取异常（原件保留、登记表锁存只读）")
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
                self.load_errors[record.repo_id] = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "库 %s(%s) 加载失败，跳过（登记保留）: %s", record.name, record.repo_id, exc
                )

    def _load_index(self) -> None:
        """读 + 结构校验 + 原子替换内存态（校验失败抛 RepoIndexError，不动原件）。"""
        try:
            size = self.index_path.stat().st_size
        except OSError as exc:
            raise RepoIndexError(f"无法读取登记表：{exc}") from exc
        if size > MAX_INDEX_BYTES:
            raise RepoIndexError(f"登记表超过 {MAX_INDEX_BYTES} 字节上限（实际 {size}）")
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RepoIndexError(f"JSON 解析失败：{exc}") from exc
        if not isinstance(data, dict):
            raise RepoIndexError("登记表顶层必须是对象")
        rows = data.get("repos")
        if not isinstance(rows, list):
            raise RepoIndexError("登记表缺少 repos 数组")
        if len(rows) > MAX_REPOS:
            raise RepoIndexError(f"登记条目 {len(rows)} 超过上限 {MAX_REPOS}")

        records: dict[str, RepoRecord] = {}
        seen_paths: dict[str, str] = {}
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise RepoIndexError(f"第 {i} 条登记不是对象")
            rid = row.get("repo_id")
            if not isinstance(rid, str) or not rid.strip():
                raise RepoIndexError(f"第 {i} 条登记缺少 repo_id")
            if rid in records:
                raise RepoIndexError(f"登记表存在重复 repo_id：{rid}")
            root_kind = row.get("root_kind") or "external"
            if root_kind not in ("managed", "external"):
                raise RepoIndexError(f"{rid} 的 root_kind 非法：{root_kind}")
            db_path = row.get("db_path") or ""
            json_path = row.get("json_path") or ""
            if not db_path or not json_path:
                raise RepoIndexError(f"{rid} 缺少 db_path/json_path（一库 = 一 db + 一 json）")
            group_key = row.get("group_key") or None
            if group_key is not None and not isinstance(group_key, str):
                raise RepoIndexError(f"{rid} 的 group_key 非法（须为字符串或 null）")
            pkey = f"{_path_key(db_path)}|{_path_key(json_path)}"
            if pkey in seen_paths:
                raise RepoIndexError(f"{rid} 与 {seen_paths[pkey]} 登记了同一份文件（重复登记）")
            seen_paths[pkey] = rid
            records[rid] = RepoRecord(
                repo_id=rid, name=row.get("name", ""),
                note=row.get("note", ""), group=row.get("group"),
                group_key=group_key, root_kind=root_kind,
                db_path=db_path, json_path=json_path,
                managed=bool(row.get("managed", True)),
                created_at=row.get("created_at", ""), updated_at=row.get("updated_at", ""),
            )
        if DEFAULT_REPO_ID not in records:
            existing = self.records.get(DEFAULT_REPO_ID)
            if existing is None:
                raise RepoIndexError("默认库未绑定（bind_default 须先于 initialize 调用）")
            records[DEFAULT_REPO_ID] = existing
        active = data.get("active_repo_id", DEFAULT_REPO_ID)
        self.records = records
        self.active_id = active if active in records else DEFAULT_REPO_ID

    def _save_index(self) -> None:
        """原子写登记表（pid 临时名 + fsync + 带重试的 replace）。

        坏索引锁存期间一律拒绝：绝不用内存态覆盖用户原件。
        """
        if not self.index_writable:
            raise RepoIndexError(
                self.index_error or "登记表已锁存只读（载入失败），拒绝覆盖原件"
            )
        self.repos_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "active_repo_id": self.active_id,
            "repos": [asdict(r) for r in self.records.values()],
        }
        atomic_write_text(self.index_path, json.dumps(payload, ensure_ascii=False, indent=2))

    # ── 解析 ──

    def resolve(self, repo_id: str | None = None) -> RepoEntry | None:
        """解析已加载的库：repo_id 空 = 活动库；未知或未加载返回 None。"""
        target = repo_id or self.active_id
        return self.entries.get(target)

    def require(self, repo_id: str | None = None) -> RepoEntry:
        entry = self.resolve(repo_id)
        if entry is None:
            raise KeyError(repo_id or self.active_id)
        return entry

    def managed_entries(self) -> list[RepoEntry]:
        """受管且已加载的库（联合检索范围；登记序稳定）。"""
        return [self.entries[r.repo_id] for r in self.records.values() if r.repo_id in self.entries]

    def _resolve_group_key(self, group: str, *, exclude_id: str | None = None) -> str | None:
        """分组展示名 → 目录键：同名分组复用既有键，否则独立生成新键。"""
        name = group.strip()
        if not name:
            return None
        folded = name.casefold()
        for record in self.records.values():
            if record.repo_id == exclude_id or not record.group or not record.group_key:
                continue
            if record.group.strip().casefold() == folded:
                return record.group_key
        return _new_group_key()

    # ── 生命周期 ──

    async def _open(self, record: RepoRecord) -> RepoEntry:
        if record.repo_id in self.entries:
            return self.entries[record.repo_id]
        # 跨进程互斥：拿不到锁说明另一个进程在写这个库 → 跳过打开（诊断可见），
        # 而不是带着「后写者覆盖先写者」的风险硬开
        lock = SingleInstanceLock(record.db_path + ".lock")
        if not lock.acquire():
            self.load_errors[record.repo_id] = "另一个进程正在写入该库（跨进程互斥），已跳过打开"
            logger.error("库 %s 被其它进程占用，跳过打开: %s", record.repo_id, lock.path)
            raise LockError(f"库 {record.name} 正被另一个进程写入")
        try:
            db = Database(record.db_path)
            await db.connect()
            es = EventStore(db)
            await es.rebuild_fts()
            gs = GraphStore(db, json_path=record.json_path)
            await gs.load()
            if not Path(record.json_path).exists():
                await gs.save()  # 新库落一份空图：「一库 = 一 db + 一 json」即日成立
        except Exception:
            lock.release()
            raise
        entry = RepoEntry(record, db, es, gs)
        entry.lock = lock
        # 启动/开库对账一次（记录 changed 与时间，供诊断与显式刷新对比）
        entry.reconcile_changed = await gs.reconcile(es)
        entry.last_reconcile_at = _now()
        if gs.dirty:
            await gs.flush()
        self.entries[record.repo_id] = entry
        self.load_errors.pop(record.repo_id, None)
        logger.info(
            "库已打开：%s(%s) reconcile_changed=%d",
            record.name, record.repo_id, entry.reconcile_changed,
        )
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
            logger.error("库 %s 关闭异常（登记保留）: %s", repo_id, exc)
        finally:
            if entry.lock is not None:
                entry.lock.release()
                entry.lock = None
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
        """建库：先登记（原子写）后建目录，失败回滚不留孤儿目录。"""
        name = (name or "").strip()
        if not (1 <= len(name) <= MAX_NAME):
            raise ValueError(f"库名须为 1–{MAX_NAME} 字符")
        if len(note or "") > MAX_NOTE:
            raise ValueError(f"备注不得超过 {MAX_NOTE} 字符")
        if len((group or "").strip()) > MAX_GROUP:
            raise ValueError(f"分组名不得超过 {MAX_GROUP} 字符")
        if root_kind not in ("managed", "external"):
            raise ValueError(f"root_kind 非法：{root_kind}")
        if len(self.records) >= MAX_REPOS:
            raise ValueError(f"库数量已达上限 {MAX_REPOS}")

        repo_id = f"rp-{uuid.uuid4().hex[:12]}"
        if root_kind == "external":
            db_path, json_path = self._validate_external_root(root)
            group_key = None
        else:
            group_key = self._resolve_group_key(group)
            repo_dir = self.repos_root / repo_id
            if group_key:
                repo_dir = self.repos_root / group_key / repo_id
            db_path = str(repo_dir / "memory.db")
            json_path = str(repo_dir / "graph.json")
        record = RepoRecord(
            repo_id=repo_id,
            name=name, note=note,
            group=(group or "").strip() or None, group_key=group_key,
            root_kind=root_kind, db_path=db_path, json_path=json_path,
            managed=True, created_at=_now(), updated_at=_now(),
        )
        self.records[record.repo_id] = record
        # 先登记：索引写失败则不留任何磁盘痕迹
        try:
            self._save_index()
        except Exception:
            self.records.pop(record.repo_id, None)
            raise

        if root_kind != "external":
            try:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                await self._open(record)
            except Exception:
                # 回滚：摘登记 + 清掉刚建的目录，避免孤儿
                self.records.pop(record.repo_id, None)
                try:
                    self._save_index()
                except Exception:  # 回滚写失败不掩盖原始错误
                    logger.exception("建库回滚：登记表写回失败（请手工核对 %s）", repo_id)
                shutil.rmtree(Path(db_path).parent, ignore_errors=True)
                raise
        else:
            try:
                await self._open(record)
            except Exception as exc:
                # external：登记保留（文件是用户的），错误进诊断
                self.load_errors[record.repo_id] = f"{type(exc).__name__}: {exc}"
                logger.error("外部库 %s 打开失败（登记保留）: %s", repo_id, exc)
        return record

    def _validate_root_dir(self, root: str) -> Path:
        """库根**目录级**校验（external 登记 / 收养共用）：

        绝对路径 + 拒符号链接 + 禁设清单（磁盘根 / 用户主目录 / 数据根双向包含 / repos 根）。
        返回解析后的目录。文件级要求由调用方按各自语义追加。
        """
        if not root or not root.strip():
            raise ValueError("必须提供目录路径")
        lexical = Path(os.path.abspath(root))
        if lexical.is_symlink():
            raise ValueError("禁设清单：目录本身是符号链接")
        try:
            resolved = lexical.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"目录不存在或不可访问：{root}（{exc}）") from exc
        if resolved != lexical:
            raise ValueError("禁设清单：路径含符号链接或相对跳转（lexical ≠ 解析结果）")
        if not resolved.is_dir():
            raise ValueError(f"不是目录：{root}")

        home = Path.home().resolve()
        data_root = self.repos_root.parent.resolve()
        repos_root = self.repos_root.resolve()
        if resolved.parent == resolved:
            raise ValueError("禁设清单：磁盘根")
        if resolved == home:
            raise ValueError("禁设清单：用户主目录")
        if _inside(resolved, data_root):
            raise ValueError(
                f"禁设清单：位于数据根内（{data_root}）；托管库请用 managed 模式新建"
            )
        if _inside(data_root, resolved):
            raise ValueError(f"禁设清单：该目录包含数据根（{data_root}）")
        if _inside(resolved, repos_root):
            raise ValueError("禁设清单：repos 根或其中子目录")
        return resolved

    def _reject_duplicate_root(
        self, db_path: Path, json_path: Path, *, exclude_id: str | None = None
    ) -> None:
        """重复登记拒绝：同一份 db+json 不能登记两次（一库一 db 一 json）。"""
        for record in self.records.values():
            if record.repo_id == exclude_id:
                continue
            if {_path_key(record.db_path), _path_key(record.json_path)} == {
                _path_key(db_path), _path_key(json_path)
            }:
                raise RepoConflictError(
                    f"该路径已登记为库 {record.name}({record.repo_id})"
                )

    def _validate_external_root(
        self, root: str, *, exclude_id: str | None = None
    ) -> tuple[str, str]:
        """external root 校验：目录级校验 + 拒符号链接 + 两文件齐备 + 重复登记拒绝。"""
        resolved = self._validate_root_dir(root)
        db_path = resolved / "memory.db"
        json_path = resolved / "graph.json"
        for f in (db_path, json_path):
            if f.is_symlink():
                raise ValueError(f"禁设清单：{f.name} 是符号链接")
        if not db_path.is_file() or not json_path.is_file():
            raise ValueError("目录中须同时存在 memory.db 与 graph.json 才可登记为库")
        self._reject_duplicate_root(db_path, json_path, exclude_id=exclude_id)
        return str(db_path), str(json_path)

    async def adopt_repo(
        self, *, root: str, name: str, note: str = "", group: str = "",
        adopt_missing: bool = True,
    ) -> dict:
        """**收养**既有目录（v1.32）：目录里至少有一个库文件即可登记为 external 书目。

        为什么需要它：`external` 登记要求两文件齐备，半损状态（`graph.json` 被误删、
        只有一份 `memory.db` 要接管）无出路。收养的语义：

        1. 目录级校验（禁设清单照旧）+ 重复登记拒绝（409）；
        2. `memory.db` / `graph.json` **至少有一个**，否则拒绝（那是「新建」不是「收养」）；
        3. 缺哪个补哪个（`adopt_missing=True`）：缺 db → 用 `Database` 建**空库并建好当前
           schema**（不手写 SQL）；缺 json → 落一份带 `format_version` 的空图层，且
           **顺带尝试从 `graph_ops` 重放恢复图层**（`GraphStore.load()` 的既有恢复链，
           恢复不了就留空图，绝不报错）。**只补空件，绝不覆盖已存在的文件**；
        4. 登记为 **external** 书目（不移动文件、不建受管目录），随后尝试打开。

        返回 `{repo_id, name, created}`；`created` 是实际补出来的文件名列表。
        """
        name = (name or "").strip()
        if not (1 <= len(name) <= MAX_NAME):
            raise ValueError(f"库名须为 1–{MAX_NAME} 字符")
        if len(note or "") > MAX_NOTE:
            raise ValueError(f"备注不得超过 {MAX_NOTE} 字符")
        if len((group or "").strip()) > MAX_GROUP:
            raise ValueError(f"分组名不得超过 {MAX_GROUP} 字符")
        if len(self.records) >= MAX_REPOS:
            raise ValueError(f"库数量已达上限 {MAX_REPOS}")

        resolved = self._validate_root_dir(root)
        db_path = resolved / "memory.db"
        json_path = resolved / "graph.json"
        for f in (db_path, json_path):
            if f.is_symlink():
                raise ValueError(f"禁设清单：{f.name} 是符号链接")
        self._reject_duplicate_root(db_path, json_path)

        has_db = db_path.is_file()
        has_json = json_path.is_file()
        existing = [p.name for p in (db_path, json_path) if p.is_file()]
        missing = [p.name for p in (db_path, json_path) if not p.is_file()]
        if not existing:
            raise ValueError(
                f"目录中既没有 memory.db 也没有 graph.json：{resolved}"
                "（这不是「收养」而是「新建」，请用 managed 建库）"
            )
        if missing and not adopt_missing:
            raise ValueError(
                f"目录中只有 {'、'.join(existing)}，缺 {'、'.join(missing)}；"
                "adopt_missing=false 时不补空件（如需补请置为 true）"
            )

        created: list[str] = []
        if missing:
            # 空库走 Database 的建表路径（当前 schema + 迁移），不手写 SQL
            database = Database(str(db_path))
            await database.connect()
            try:
                if not has_db:
                    created.append("memory.db")
                if not has_json:
                    gs = GraphStore(database, json_path=str(json_path))
                    # 文件缺失 → 既有恢复链会尝试从 graph_ops 重放；恢复不了就是空图
                    await gs.load()
                    await gs.save()  # 落一份带 format_version 的图层文件
                    created.append("graph.json")
            finally:
                await database.close()

        repo_id = f"rp-{uuid.uuid4().hex[:12]}"
        record = RepoRecord(
            repo_id=repo_id,
            name=name, note=note,
            group=(group or "").strip() or None, group_key=None,
            root_kind="external",
            db_path=str(db_path), json_path=str(json_path),
            managed=True, created_at=_now(), updated_at=_now(),
        )
        self.records[record.repo_id] = record
        # 先登记：索引写失败则摘掉内存登记（补出来的空件留在原地，用户可重试）
        try:
            self._save_index()
        except Exception:
            self.records.pop(record.repo_id, None)
            raise
        try:
            await self._open(record)
        except Exception as exc:
            # external：登记保留（文件是用户的），错误进诊断（load_error 可见）
            self.load_errors[record.repo_id] = f"{type(exc).__name__}: {exc}"
            logger.error("收养的库 %s 打开失败（登记保留）: %s", repo_id, exc)
        logger.info(
            "目录已收养：%s(%s) root=%s created=%s",
            name, repo_id, resolved, created or "无",
        )
        return {"repo_id": repo_id, "name": name, "created": created}

    async def update_repo(
        self, repo_id: str, *, name: str | None = None, note: str | None = None,
        group: str | None = None, managed: bool | None = None, root: str | None = None,
    ) -> RepoRecord:
        """改名/备注/改分组（managed 真迁移 + 回滚）/受管开关/external 重指向。"""
        record = self.records.get(repo_id)
        if record is None:
            raise KeyError(repo_id)

        changes: dict = {}
        if name is not None:
            new_name = name.strip()
            if not (1 <= len(new_name) <= MAX_NAME):
                raise ValueError(f"库名须为 1–{MAX_NAME} 字符")
            changes["name"] = new_name
        if note is not None:
            if len(note) > MAX_NOTE:
                raise ValueError(f"备注不得超过 {MAX_NOTE} 字符")
            changes["note"] = note
        if managed is not None and managed != record.managed and repo_id != DEFAULT_REPO_ID:
            changes["managed"] = managed

        move: tuple[Path, Path] | None = None
        if group is not None and record.root_kind == "managed":
            gname = group.strip()
            if len(gname) > MAX_GROUP:
                raise ValueError(f"分组名不得超过 {MAX_GROUP} 字符")
            new_key = self._resolve_group_key(gname, exclude_id=repo_id)
            if new_key != record.group_key:
                changes["group"] = gname or None
                changes["group_key"] = new_key
                old_dir = Path(record.db_path).parent
                new_dir = self.repos_root / repo_id
                if new_key:
                    new_dir = self.repos_root / new_key / repo_id
                if old_dir != new_dir:
                    move = (old_dir, new_dir)
        if root is not None:
            # 受管库目录由系统管理（`repos/<group_key>/<repo_id>/`）：重指向无意义且会
            # 让登记与目录布局脱钩，一律拒绝（API 层映射 400）
            if record.root_kind != "external":
                raise ValueError(
                    "受管库目录由系统管理，不支持 root 重指向（仅外部库可换目录）"
                )
            db_path, json_path = self._validate_external_root(root, exclude_id=repo_id)
            if _path_key(db_path) != _path_key(record.db_path) or (
                _path_key(json_path) != _path_key(record.json_path)
            ):
                changes["db_path"] = db_path
                changes["json_path"] = json_path

        if not changes:
            return record

        old = record
        new_record = replace(record, updated_at=_now(), **changes)
        was_loaded = repo_id in self.entries

        # 需要动文件/换句柄时先关闭（Windows 下打开着的库目录无法改名）
        need_reopen = was_loaded or changes.get("managed") is True
        if was_loaded and (move is not None or "db_path" in changes or changes.get("managed") is False):
            await self._close(repo_id)

        moved = False
        if move is not None:
            old_dir, new_dir = move
            if new_dir.exists():
                if was_loaded:
                    await self._open(old)
                raise ValueError(f"目标分组目录已存在：{new_dir}")
            try:
                new_dir.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old_dir, new_dir)
                moved = True
            except OSError as exc:
                if was_loaded:
                    await self._open(old)
                raise ValueError(f"分组迁移失败（登记未改动）：{exc}") from exc

        self.records[repo_id] = new_record
        if changes.get("managed") is False and self.active_id == repo_id:
            self.active_id = DEFAULT_REPO_ID
        try:
            self._save_index()
        except Exception:
            # 登记写失败：目录与内存登记双双回滚
            self.records[repo_id] = old
            if moved and move is not None:
                old_dir, new_dir = move
                try:
                    os.replace(new_dir, old_dir)
                except OSError:
                    logger.exception("分组迁移回滚失败，请手工核对目录：%s", new_dir)
            if was_loaded and repo_id not in self.entries:
                await self._open(old)
            raise

        if need_reopen and changes.get("managed") is not False and repo_id not in self.entries:
            try:
                await self._open(self.records[repo_id])
            except Exception as exc:
                self.load_errors[repo_id] = f"{type(exc).__name__}: {exc}"
                logger.error("库 %s 重新加载失败（登记已生效）: %s", repo_id, exc)
        return new_record

    async def delete_repo(self, repo_id: str) -> None:
        """摘除登记（不删任何磁盘文件）；默认库与活动库不可摘。"""
        if repo_id == DEFAULT_REPO_ID:
            raise ValueError("默认库不可摘除")
        if self.active_id == repo_id:
            raise ValueError("活动库不可摘除，请先切换活动库")
        record = self.records.pop(repo_id, None)
        if record is None:
            raise KeyError(repo_id)
        try:
            self._save_index()
        except Exception:
            self.records[repo_id] = record  # 写失败：登记在内存里还原
            raise
        await self._close(repo_id)
        self.load_errors.pop(repo_id, None)

    # ── 登记表重建 / 书目清除（v1.31）──

    def _scan_managed_repo_dirs(self) -> list[Path]:
        """扫描受管库根下「含 memory.db 或 graph.json」的目录（新到旧无关，按路径排序）。

        排除 `backups/`、`trash/` 内的副本：整库备份目录里就有一份 `memory.db`，
        若把它当成库目录，重建会把备份登记成书目（数据面被污染）。
        """
        root = self.repos_root
        if not root.is_dir():
            return []
        found: dict[str, Path] = {}
        for name in ("memory.db", "graph.json"):
            for item in root.glob(f"**/{name}"):
                parent = item.parent
                parts = {p.casefold() for p in parent.relative_to(root).parts}
                if parts & {n.casefold() for n in NON_REPO_DIRNAMES}:
                    continue
                found[_path_key(parent)] = parent
        return [found[key] for key in sorted(found)]

    async def rebuild_index(self) -> dict:
        """重建 `repos/index.json` 登记表（坏索引恢复入口，v1.31）。

        语义：

        1. **清掉只读锁存**（重建成功即恢复可写；失败则还原锁存态）；
        2. 扫描磁盘上可识别的库：受管库根下每个含 `memory.db` 或 `graph.json` 的目录
           （排除 `backups/`、`trash/` 内的副本）+ **现役默认库** + **仍存在的外部库根**；
        3. 重建登记表并保存。**绝不删除任何磁盘数据文件**（只写 `repos/index.json`）。

        诚实边界：受管库的显示名/备注/分组与休眠标记只存在于登记表，磁盘上没有痕迹——
        能按路径对上的沿用旧记录，对不上的以**目录名**为显示名、`group_key` 取分组目录名
        （`grp_*` / `grp-*`），重塑库一律按受管恢复；新登记的库需重启或
        `POST /repos/{id}/refresh` 才会加载。
        """
        latched_before = not self.index_writable
        previous_records = self.records
        previous_active = self.active_id
        previous_error = self.index_error
        previous_writable = self.index_writable

        # 旧记录只作「路径 → 元信息」提示（坏索引时可能只剩默认库，属预期）
        hints: dict[str, RepoRecord] = {}
        for record in [*self.records.values(), *(e.record for e in self.entries.values())]:
            hints.setdefault(_path_key(record.db_path), record)

        records: dict[str, RepoRecord] = {}
        used_ids: set[str] = set()

        def _add(record: RepoRecord) -> None:
            if record.repo_id in used_ids:
                return
            used_ids.add(record.repo_id)
            records[record.repo_id] = record

        # 1) 现役默认库（现行配置为真源）
        default = self.records.get(DEFAULT_REPO_ID) or RepoRecord(
            repo_id=DEFAULT_REPO_ID, name="默认库", root_kind="external"
        )
        _add(replace(
            default,
            repo_id=DEFAULT_REPO_ID,
            name=default.name or "默认库",
            db_path=str(Path(settings.memory_db_path).resolve()),
            json_path=str(Path(settings.graph_json_path).resolve()),
            updated_at=_now(),
        ))

        # 2) 受管库目录扫描
        for directory in self._scan_managed_repo_dirs():
            db_path = str(directory / "memory.db")
            json_path = str(directory / "graph.json")
            hint = hints.get(_path_key(db_path))
            repo_id = hint.repo_id if hint else (
                directory.name if directory.name.startswith("rp") else f"rp-{uuid.uuid4().hex[:12]}"
            )
            if repo_id in used_ids:  # 目录名撞上已用 id：退让为独立生成
                repo_id = f"rp-{uuid.uuid4().hex[:12]}"
            parent = directory.parent
            scanned_group_key = (
                parent.name
                if parent != self.repos_root
                and parent.name.startswith((GROUP_KEY_PREFIX, _LEGACY_GROUP_KEY_PREFIX))
                else None
            )
            group_key = (hint.group_key if hint else None) or scanned_group_key
            _add(RepoRecord(
                repo_id=repo_id,
                name=hint.name if hint else directory.name,
                note=hint.note if hint else "",
                group=(hint.group if hint else None) or group_key,
                group_key=group_key,
                root_kind="managed",
                db_path=db_path,
                json_path=json_path,
                managed=hint.managed if hint else True,
                created_at=hint.created_at if hint else _now(),
                updated_at=_now(),
            ))

        # 3) 仍存在的外部库根（外部目录不在扫描范围内，只能靠旧登记提示）
        for record in [*self.records.values(), *(e.record for e in self.entries.values())]:
            if record.root_kind != "external" or record.repo_id == DEFAULT_REPO_ID:
                continue
            if not Path(record.db_path).parent.is_dir():
                continue  # 外部库根已不存在 → 不重建
            _add(replace(record, updated_at=_now()))

        self.records = records
        self.active_id = previous_active if previous_active in records else DEFAULT_REPO_ID
        self.index_error = ""
        self.index_writable = True
        try:
            self._save_index()
        except Exception:
            self.records = previous_records
            self.active_id = previous_active
            self.index_error = previous_error
            self.index_writable = previous_writable
            raise
        # 已不在登记表里的运行中库：关掉（登记已摘，句柄不该继续占着）
        for repo_id in list(self.entries):
            if repo_id not in records:
                await self._close(repo_id)
        added = [rid for rid in records if rid not in previous_records]
        dropped = [rid for rid in previous_records if rid not in records]
        logger.info(
            "登记表已重建：%d 个库（新增 %s，移除 %s，重建前锁存=%s）",
            len(records), added or "无", dropped or "无", latched_before,
        )
        return {
            "repos": len(records),
            "latched_before": latched_before,
            "added": added,
            "dropped": dropped,
        }

    def _remove_repo_files(self, record: RepoRecord) -> list[str]:
        """删除受管库的数据文件（只动受管库根之内的文件，绝不越界）。

        删除清单：`memory.db`（含 `-wal`/`-shm`/`.lock`）+ `graph.json` 及其 `.bak*`。
        **库目录本身保留**——其中的 `backups/` 正是清除前那份安全备份，删掉就白备份了。
        """
        removed: list[str] = []
        root = self.repos_root.resolve()
        db = Path(record.db_path)
        json_path = Path(record.json_path)
        targets: list[Path] = [
            db,
            db.with_name(db.name + "-wal"),
            db.with_name(db.name + "-shm"),
            db.with_name(db.name + ".lock"),
            json_path,
        ]
        targets.extend(json_path.parent.glob(json_path.name + ".bak*"))
        for target in targets:
            try:
                resolved = target.resolve()
            except OSError:
                continue
            if not _inside(resolved, root):  # 越界（外部路径/上级目录）一律跳过
                logger.warning("清除库时跳过越界路径: %s", target)
                continue
            if not resolved.is_file():
                continue
            try:
                resolved.unlink()
                removed.append(str(resolved))
            except OSError as exc:
                logger.warning("库文件删除失败（不影响摘登记）: %s (%s)", resolved, exc)
        return removed

    async def purge_repo(self, repo_id: str, *, note: str = "") -> dict:
        """清除书目（v1.31）：**先整库备份 → 删库文件 → 摘登记**。

        - **默认库与活动库拒绝**（这里兜底；API 层映射 400/409 并给出中文原因）；
        - **受管库**：先 `create_backup`（备份失败即**中止**，绝不在没有备份的情况下删数据），
          再删 `memory.db`（含 `-wal`/`-shm`/`.lock`）与 `graph.json` 及其 `.bak*`；
        - **外部库**：只摘登记，**不删外部目录任何文件**（也就无需备份，`backup_path` 为空）；
        - 顺序为「先摘登记、后删文件」：删文件失败只留下孤儿文件，
          不会出现「登记说在、文件已经没了」。
        """
        record = self.records.get(repo_id)
        if record is None:
            raise KeyError(repo_id)
        if repo_id == DEFAULT_REPO_ID:
            raise ValueError("默认库不可清除（默认库是现役数据根）")
        if self.active_id == repo_id:
            raise ValueError("活动库不可清除，请先切换活动库")

        managed = record.root_kind == "managed"
        backup_path = ""
        backup_note = ""
        entry = self.entries.get(repo_id)
        if managed:
            if entry is None:
                # 休眠/未加载的受管库：开一次以便备份（即将删除，加载无副作用）
                try:
                    entry = await self._open(record)
                except Exception as exc:
                    backup_note = f"库无法打开（{type(exc).__name__}: {exc}），未做备份"
                    logger.error("清除库 %s 前无法打开：%s", repo_id, exc)
            if entry is not None and str(record.db_path) != ":memory:":
                try:
                    result = await create_backup(
                        entry.db, entry.graph_store, note=note or f"清除库 {record.name}"
                    )
                    backup_path = str(result.get("backup_dir") or "")
                except Exception as exc:
                    raise ValueError(
                        f"清除前备份失败，已中止（绝不在没有备份的情况下删数据）：{exc}；"
                        f"如确认要放弃数据，请改用 DELETE /repos/{repo_id} 仅摘除登记"
                    ) from exc
        else:
            backup_note = "外部库只摘登记、不删外部目录文件，故未做备份"

        # 摘登记（内部会 _close：释放 db 句柄与跨进程锁，Windows 下才能删文件）
        await self.delete_repo(repo_id)
        deleted = self._remove_repo_files(record) if managed else []

        if managed:
            message = (
                f"库已清除：{record.name}（{repo_id}）——"
                f"备份 {backup_path or '未生成'}；"
                f"已删除库文件 {len(deleted)} 个（memory.db / graph.json 及其 -wal·-shm·.bak）"
            )
        else:
            message = (
                f"外部库已摘除登记：{record.name}（{repo_id}）——"
                "未删除外部目录中的任何文件（备份亦未生成）"
            )
        if backup_note:
            message = f"{message}；{backup_note}"
        logger.info("库已清除：%s(%s) 删除文件 %d 个", record.name, repo_id, len(deleted))
        return {
            "message": message,
            "backup_path": backup_path,
            "deleted": deleted,
            "root_kind": record.root_kind,
        }

    async def activate(self, repo_id: str) -> None:
        record = self.records.get(repo_id)
        if record is None:
            raise KeyError(repo_id)
        if not record.managed:
            raise ValueError("未受管的库不能设为活动库")
        previous = self.active_id
        self.active_id = repo_id
        try:
            self._save_index()
        except Exception:
            self.active_id = previous
            raise

    async def refresh_repo(self, repo_id: str) -> dict:
        """显式修复/刷新：确保已加载 → 对账 source_refs → 脏则落盘 → 返回统计。

        对应「图层损坏/悬空源证只能重启才对账」的缺口：给界面一个可触发的入口。
        """
        record = self.records.get(repo_id)
        if record is None:
            raise KeyError(repo_id)
        if not record.managed:
            raise ValueError("休眠库不参与加载与修复（请先切回受管）")
        entry = await self._open(record)
        changed = await entry.graph_store.reconcile(entry.event_store)
        entry.reconcile_changed = changed
        entry.last_reconcile_at = _now()
        if entry.graph_store.dirty:
            await entry.graph_store.flush()
        return {
            "repo_id": repo_id,
            "name": record.name,
            "events": await entry.event_store.total_events(),
            "nodes": entry.graph_store.total_nodes(),
            "edges": entry.graph_store.total_edges(),
            "changed": changed,
            "last_reconcile_at": entry.last_reconcile_at,
        }

    def load_error_of(self, repo_id: str) -> str:
        """**未加载原因**（v1.32，P6 失败可见）：只读汇总，**不改变任何加载行为**。

        取值顺序：

        1. 已加载 → 空串；
        2. **显式加载失败原因优先**（`load_errors`：跨进程锁占用 / 开库异常等）；
        3. 磁盘问题（更要紧、更可下手）：库目录不存在 / 登记文件缺失；
        4. 休眠（未受管）——磁盘没问题时的原因就是「用户主动关了」；
        5. 文件都在却没加载（罕见）→ 空串，不编造原因。
        """
        if repo_id in self.entries:
            return ""
        explicit = self.load_errors.get(repo_id, "")
        if explicit:
            return explicit
        record = self.records.get(repo_id)
        if record is None:
            return ""
        db_path = Path(record.db_path)
        json_path = Path(record.json_path)
        if not db_path.parent.is_dir():
            return f"库目录不存在：{db_path.parent}（登记仍在，可重指向或摘除）"
        missing = [p.name for p in (db_path, json_path) if not p.is_file()]
        if missing:
            return f"登记文件缺失：{'、'.join(missing)}（库目录 {db_path.parent}）"
        if not record.managed:
            return "库处于休眠（未受管）：不加载、不检索、不构图（切回受管即恢复）"
        return ""

    async def diagnostics(self) -> list[dict]:
        """库可用性诊断：不打开库文件即可给出（missing/root_error/load_error/计数）。"""
        out: list[dict] = []
        for record in self.records.values():
            db_path = Path(record.db_path)
            json_path = Path(record.json_path)
            entry = self.entries.get(record.repo_id)
            missing = [p.name for p in (db_path, json_path) if not p.exists()]
            root_error = ""
            root_dir = db_path.parent
            if not root_dir.exists():
                root_error = "库目录不存在"
            elif not root_dir.is_dir():
                root_error = "库目录不是目录"
            out.append({
                "repo_id": record.repo_id,
                "name": record.name,
                "group": record.group,
                "group_key": record.group_key,
                "legacy_group_key": is_legacy_group_key(record.group_key),
                "root_kind": record.root_kind,
                "managed": record.managed,
                "active": record.repo_id == self.active_id,
                "loaded": entry is not None,
                "db_path": record.db_path,
                "json_path": record.json_path,
                "missing": missing,
                "root_error": root_error,
                "load_error": self.load_errors.get(record.repo_id, ""),
                "total_events": (await entry.event_store.total_events()) if entry else None,
                "total_nodes": entry.graph_store.total_nodes() if entry else None,
                "total_edges": entry.graph_store.total_edges() if entry else None,
                "last_reconcile_at": entry.last_reconcile_at if entry else "",
                "reconcile_changed": entry.reconcile_changed if entry else None,
            })
        return out


def fuse_joint_results(
    per_repo: list[tuple[RepoEntry, SearchResponse]],
) -> tuple[list[SearchResult], dict]:
    """库间融合（v1.29 联合检索 / v1.30 加融合轨迹）：等权 RRF + 去重 + 来源锚定。

    去重键：事件 = content_hash（缺省退回 event_id）；节点 = (类型, 标题归一)。
    被合并项保留首命中负载，`source_repos` 列出全部来源库名。

    返回 `(results, stats)`；`stats["contribs"]` 与 results **下标一一对应**，
    每项是该结果在各库的 `{repo_id, repo_name, rank, score, rrf}` 贡献明细（融合轨迹）。
    """
    merged: dict[tuple, dict] = {}
    deduped = 0
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
                    "contribs": [],
                }
                # 来源库锚定：首命中库写入 repo_id/repo_name
                item["hit"].repo_id = entry.repo_id
                item["hit"].repo_name = entry.name
                merged[key] = item
            else:
                deduped += 1
            item["score"] += gain
            item["contribs"].append(
                {
                    "repo_id": entry.repo_id,
                    "repo_name": entry.name,
                    "rank": rank,
                    "score": hit.score,
                    "rrf": gain,
                }
            )
            if entry.name not in item["repos"]:
                item["repos"].append(entry.name)
    results: list[SearchResult] = []
    contribs: list[list[dict]] = []
    for item in merged.values():
        hit: SearchResult = item["hit"]
        hit.score = item["score"]
        hit.source_repos = item["repos"]
        results.append(hit)
        contribs.append(item["contribs"])
    return results, {
        "merged_total": len(results),
        "deduped": deduped,
        "contribs": contribs,
    }
