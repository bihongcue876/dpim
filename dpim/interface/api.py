"""FastAPI 应用装配：lifespan / 中间件 / router 挂载。

REST 端点按职责拆到 `interface/routers/*`（纯搬移：路径、方法、状态码、
响应模型与拆分前逐一对应；v1.31 起端点总数 42）；共享状态（`db` / `event_store` /
`graph_store` / `repos` / `orchestrator` / `compensator`）与共享工具在
`interface/deps.py`——router 一律 `from interface import deps` 后在**调用时**
读 `deps.xxx`，测试替换这些全局即刻生效。

本模块保留：`app`、`lifespan`、两个 HTTP 中间件、`_flush_loaded_repos`
（app 级写收口）。`from interface.api import app` 仍是唯一应用入口
（`main.py` / `uvicorn interface.api:app` / 测试均依赖它）。
"""

import asyncio
import contextlib
import logging
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from controller.compensator import Compensator
from controller.orchestrator import Orchestrator
from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_ops import compact_ops
from core.graph_store import GraphStore
from core.logging_setup import setup_file_logging
from core.repos import RepoManager
from core.state import refresh_key
from core.trash import prune_trash
from interface import deps
from interface.routers import (
    agent_router,
    events_router,
    logs_router,
    maintenance_router,
    nodes_router,
    query_router,
    repos_router,
    settings_router,
    trash_router,
)

logger = logging.getLogger(__name__)

# 保留策略检查节流（秒）：压实/清理都是「看一眼再决定动不动」的廉价操作，
# 没必要跟着 WAL 周期（默认 300s）跑——每小时一次足够，且启动时先跑一次。
_RETENTION_EVERY_SECONDS = 3600


async def _run_retention_once() -> dict[str, int]:
    """对所有已加载库跑一轮保留策略（v1.39）：graph_ops 压实 + 回收站过期留档清理。

    **压实而非截断**：`graph_ops` 是「graph.json 丢失/损坏且无备份时的重放恢复依据」，
    直接删老 op 会让重放只能还原后半段（恢复不完整、`verify` 恒红）——`compact_ops`
    把最老明细换成等价快照，重放结果不变。回收站则按年龄清（留档是已删数据的最后一份副本）。

    失败只记日志不抛出：这是后台卫生工作，绝不该影响服务可用性。
    """
    out = {"repos": 0, "compacted": 0, "ops_removed": 0, "trash_removed": 0}
    if deps.repos is None:
        return out
    for entry in list(deps.repos.entries.values()):
        out["repos"] += 1
        try:
            result = await compact_ops(entry.db.conn, keep=settings.graph_ops_retention)
            if result["compacted"]:
                out["compacted"] += 1
                out["ops_removed"] += result["removed"]
        except Exception:
            logger.exception("graph_ops 压实失败（库 %s，继续）", entry.repo_id)
        try:
            pruned = prune_trash(entry.db.db_path, settings.trash_retention_days)
            out["trash_removed"] += pruned["removed"]
        except Exception:
            logger.exception("回收站清理失败（库 %s，继续）", entry.repo_id)
    return out


async def _storage_housekeeping_loop() -> None:
    """周期性存储卫生：保留策略（压实/清理）+ WAL 超阈值 checkpoint(TRUNCATE)。

    ① 保留策略（v1.39）：`graph_ops` 表与 `trash/` 目录此前**只增不减**。并入本循环
    （两者都是「看一眼再决定动不动」的廉价操作，共用一次遍历已加载库的开销），
    另有节流——最多每 `_RETENTION_EVERY_SECONDS` 跑一次，启动时先跑一次。
    ② WAL 治理（P4）：此前全仓没有任何 checkpoint → 长期运行 WAL 无界增长；
    只做「超阈值才动」，避免频繁截断影响写性能。
    """
    last_retention = 0.0
    first_pass = True
    while True:
        now = time.time()
        if now - last_retention >= _RETENTION_EVERY_SECONDS:
            last_retention = now
            try:
                stats = await _run_retention_once()
                # 启动那一轮**无论有没有动作都留一行**（否则「跑过了」无从查证）；
                # 之后只在真的压实/清理时记，避免每小时刷一行噪声
                if stats["compacted"] or stats["trash_removed"] or first_pass:
                    logger.info(
                        "保留策略：检查 %d 个库（保留 op %d 条 / 留档 %d 天）→ "
                        "压实 %d 个库（压掉 %d 条 op）/ 清理过期留档 %d 份",
                        stats["repos"], settings.graph_ops_retention,
                        settings.trash_retention_days, stats["compacted"],
                        stats["ops_removed"], stats["trash_removed"],
                    )
                first_pass = False
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("保留策略轮次异常（继续）")
        await asyncio.sleep(max(30, settings.wal_checkpoint_interval))
        try:
            entries = (
                list(deps.repos.entries.values()) if deps.repos is not None else []
            )
            for entry in entries:
                try:
                    size = await entry.db.wal_size()
                    if size <= settings.wal_checkpoint_bytes:
                        continue
                    busy, log_frames, done = await entry.db.checkpoint("TRUNCATE")
                    logger.info(
                        "WAL 检查点 %s: 触发阈值=%d 当前=%d busy=%d 帧=%d/%d",
                        entry.repo_id, settings.wal_checkpoint_bytes, size,
                        busy, log_frames, done,
                    )
                except Exception:
                    logger.exception("WAL 检查点失败（库 %s，继续）", entry.repo_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("WAL 治理循环异常（继续）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 本地日志系统（前后端分文件）：最先就位，启动期失败也能落到文件里
    setup_file_logging()
    deps.db = Database()
    await deps.db.connect()
    deps.event_store = EventStore(deps.db)
    # 启动自愈：events_fts 全量重建（T0-3，修「事件存在但检索不到」遗留）
    await deps.event_store.rebuild_fts()
    deps.graph_store = GraphStore(deps.db)
    await deps.graph_store.load()
    # 启动自愈：图 source_refs 与事件表现状对齐（悬空/漂移源证置 invalid）
    await deps.graph_store.reconcile(deps.event_store)
    await deps.graph_store.flush()
    # 库管理（v1.29）：现行三件套绑定为默认库（external 登记，零移动迁移），
    # 再读登记表打开其它受管库
    deps.repos = RepoManager()
    deps.repos.bind_default(deps.db, deps.event_store, deps.graph_store)
    await deps.repos.initialize()
    deps.orchestrator = Orchestrator(
        deps.db, deps.event_store, deps.graph_store, repos=deps.repos
    )
    deps.orchestrator.start()
    deps.compensator = Compensator(
        deps.event_store, deps.graph_store, deps.orchestrator.enqueue, repos=deps.repos
    )
    deps.compensator.start()
    # 存储卫生周期任务（P4 + v1.39）：保留策略（graph_ops 压实 / 回收站清理）+ WAL 检查点
    wal_task = asyncio.create_task(_storage_housekeeping_loop())
    try:
        yield
    finally:
        wal_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await wal_task
        if deps.compensator:
            await deps.compensator.stop()
        if deps.orchestrator:
            await deps.orchestrator.stop()
        if deps.repos:
            await deps.repos.close()
        if deps.graph_store and deps.graph_store.dirty:
            await deps.graph_store.save()
        if deps.db:
            await deps.db.close()


app = FastAPI(title="DPIM", version="0.4.0", lifespan=lifespan)


@app.middleware("http")
async def auth_guard(request, call_next):
    """API 访问认证：DPIM_API_KEY 非空时，所有端点要求 X-API-Key 头匹配。

    默认（DPIM_API_KEY 空）完全放行，本地实验零配置不受影响；
    部署到服务器时设置该环境变量即启用整体保护（含 /settings、/agent/logs 等敏感端点）。
    """
    expected = settings.api_key
    # compare_digest：常数时间比较，防 timing 侧信道逐字节猜测密钥
    if expected and not secrets.compare_digest(
        request.headers.get("X-API-Key", ""), expected
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized: missing or invalid X-API-Key header"},
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return await call_next(request)


async def _flush_loaded_repos() -> int:
    """写路径统一收口：把已加载库的脏图落盘，返回落盘库数。

    一处收口替代散落在各端点的 `gs.flush()`，并覆盖「改了图却忘记落盘」的路径。
    脏位为假时是空操作，因此反复调用无代价。
    """
    if deps.repos is None:
        if deps.graph_store is not None and deps.graph_store.dirty:
            await deps.graph_store.flush()
            return 1
        return 0
    flushed = 0
    for entry in list(deps.repos.entries.values()):
        store = entry.graph_store
        if store is not None and store.dirty:
            await store.flush()
            flushed += 1
    return flushed


# 状态校验密钥免刷白名单（**路径 + 方法精确匹配**，不用前缀——防误豁免一片端点）：
# `POST /logs/client` 是前端日志上报，属**旁路**而非数据写入。若它也刷新密钥，
# 前端只要有一次请求失败就上报一条日志 → 密钥随之变化 → 变成噪声，
# 让「写前比对密钥」的护栏无谓地要求用户刷新页面。读侧同理（`GET /logs` 只读）。
_NO_REFRESH_WRITES = {("POST", "/logs/client")}


def _skips_key_refresh(request) -> bool:
    return (request.method, request.url.path) in _NO_REFRESH_WRITES


@app.middleware("http")
async def write_commit(request, call_next):
    """写请求统一收口：落盘脏图 + 刷新状态校验密钥 + 记录写操作流水。

    非 GET/HEAD/OPTIONS 请求在 handler 之后依次做三件事：

    1. **落盘**：`_flush_loaded_repos()`；失败返回 500——写已生效但没落盘必须可见，
       绝不静默丢修改（与原子写的 fail-closed 语义一致）。
    2. **刷新状态密钥**：`StateKey.refresh()` 生成的是**随机 UUID**（非状态派生），
       故只在成功（<400）时刷新，避免失败请求让前端做无谓重取；
       `_NO_REFRESH_WRITES`（当前仅 `POST /logs/client`）是显式豁免——
       日志上报不改数据，刷密钥只会制造噪声。
    3. **写操作流水**：方法/路径/状态/耗时/落盘库数，落 `logs/backend-*.log`
       （前端日志另落 `frontend-*.log`），供本地翻看。豁免项**照常记流水**。
    """
    started = time.perf_counter()
    response = await call_next(request)
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return response
    try:
        flushed = await _flush_loaded_repos()
    except Exception as exc:
        logger.exception("写请求落盘失败: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Write applied but persistence failed: {exc}"},
        )
    if response.status_code < 400 and not _skips_key_refresh(request):
        refresh_key()
    repo_hint = request.query_params.get("repo_id") or ""
    logger.info(
        "写操作 %s %s → %s (%.0fms) flush=%d%s",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
        flushed,
        f" repo={repo_hint}" if repo_hint else "",
    )
    return response


# ── 端点挂载（拆分后统一入口；路径与拆分前完全一致）──────────────
app.include_router(events_router)
app.include_router(nodes_router)
app.include_router(query_router)
app.include_router(repos_router)
app.include_router(agent_router)
app.include_router(maintenance_router)
app.include_router(settings_router)
app.include_router(logs_router)
app.include_router(trash_router)
