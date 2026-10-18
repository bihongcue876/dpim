"""interface 层共享状态与共享工具（api.py 拆分后的单一真相源）。

**纪律**：`db / event_store / graph_store / repos / orchestrator / compensator`
是**模块级可变全局**（`lifespan` 装配，测试直接替换绑定）。router 模块只能：

    from interface import deps
    ...
    deps.event_store          # 调用时取值，始终是最新绑定

绝不能 `from interface.deps import event_store`——那拿到的是导入时刻的旧绑定，
替换后 router 看不见（`test_integration` / `test_repos` / `test_security` /
`test_commands` / `test_joint_search` / `test_maintenance_api` / `test_write_commit`
都直接改这些全局）。

本模块只放「共享状态 + 无副作用工具」，不放任何路由；`_flush_loaded_repos`
与两个中间件留在 `interface/api.py`（它们是 app 级收口）。
"""

import logging
from typing import Any

from fastapi import HTTPException

from controller.compensator import Compensator
from controller.orchestrator import Orchestrator
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import EventStatus, IngestResponse
from core.repos import RepoManager

# interface 层统一 logger：拆分前所有 interface 日志都出自 interface/api.py，
# 这里显式沿用同一名字，日志格式里的 %(name)s 保持不变（拆分零观感变化）。
logger = logging.getLogger("interface.api")

# 事件状态转换白名单：raw→linked 等绕过管线的转换一律拒绝
ALLOWED_EVENT_TRANSITIONS = {
    ("raw", "indexed"),
    ("indexed", "linked"),
    ("indexed", "failed"),
    ("indexed", "skipped"),
    # 撤销入图（v1.42）：整图清空时由后端把 linked 回退为 indexed（派生链接一并撤销），
    # 人类也可显式走此转换让事件重新入队（PUT /events/{id}/status 的 indexed 分支会入队）。
    ("linked", "indexed"),
    ("failed", "indexed"),
    ("failed", "skipped"),
    ("skipped", "indexed"),
    ("skipped", "failed"),
}


def _ok(**extra: Any) -> dict[str, Any]:
    """统一成功响应信封：所有简单端点返回 status=ok + message + 可选字段。"""
    return {"status": "ok", "message": "ok", **extra}


db: Database | None = None
event_store: EventStore | None = None
graph_store: GraphStore | None = None
repos: RepoManager | None = None
orchestrator: Orchestrator | None = None
compensator: Compensator | None = None


def _resolve_repo(repo_id: str | None = None):
    """解析册条目（v1.29）：repo_id 空 = 活动库；未初始化/未加载返回 None。"""
    if repos is None:
        return None
    return repos.resolve(repo_id or None)


def _stores(repo_id: str | None = None):
    """解析册三件套：repo_id 空 = 活动库；未知/未加载 → 404。"""
    entry = _resolve_repo(repo_id)
    if entry is not None:
        return entry.event_store, entry.graph_store
    if repos is not None:
        raise HTTPException(
            status_code=404,
            detail=f"Repo not found or not loaded: {repo_id or '(active)'}",
        )
    if not event_store or not graph_store:
        raise HTTPException(status_code=503, detail="Storage not initialized")
    return event_store, graph_store


def _command_response(message: str) -> IngestResponse:
    """指令响应：未创建事件，message 携带面向用户的执行结果。"""
    return IngestResponse(
        event_id="",
        status=EventStatus.skipped,
        message=message,
        command_triggered=True,
    )


def _database(repo_id: str | None = None):
    """取库对应的 Database（活动库/指定库；未初始化 → 503）。"""
    entry = _resolve_repo(repo_id)
    if entry is not None:
        return entry.db
    if db is None:
        raise HTTPException(status_code=503, detail="Storage not initialized")
    return db


def _parse_repo_ids(value: str | None) -> list[str] | None:
    """解析 `repo_ids=a,b,c`（v1.30 联合列表）；空/未给返回 None。"""
    if not value or not value.strip():
        return None
    ids = [item.strip() for item in value.split(",") if item.strip()]
    return ids or None


def _joint_repo_entries(ids: list[str]) -> list[Any]:
    """解析联合列表的库条目（未受管/未加载 → 422，与 /query 语义一致）。"""
    if repos is None:
        raise HTTPException(status_code=503, detail="Repo manager not initialized")
    entries: list[Any] = []
    for bid in ids:
        record = repos.records.get(bid)
        if record is None or not record.managed or bid not in repos.entries:
            raise HTTPException(
                status_code=422, detail=f"Unknown or unmanaged repo: {bid}"
            )
        entries.append(repos.entries[bid])
    return entries
