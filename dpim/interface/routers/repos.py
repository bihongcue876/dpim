"""库管理 router：`/repos*`（v1.29：一库 = 一 memory.db + 一 graph.json）。"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from core.config import settings
from core.models import (
    QueueMessage,
    RepoAdoptRequest,
    RepoAdoptResponse,
    RepoCreateRequest,
    RepoInfo,
    RepoListResponse,
    RepoPurgeResponse,
    RepoRebuildResponse,
    RepoRefreshResponse,
    RepoUpdateRequest,
)
from core.repos import DEFAULT_REPO_ID, RepoConflictError
from core.state import ai_state
from interface import deps
from interface.deps import _ok, logger

router = APIRouter()


def _repo_info(repo_id: str) -> RepoInfo:
    record = deps.repos.records[repo_id]
    entry = deps.repos.entries.get(repo_id)
    return RepoInfo(
        repo_id=record.repo_id,
        name=record.name,
        note=record.note,
        group=record.group,
        root_kind=record.root_kind,
        managed=record.managed,
        active=repo_id == deps.repos.active_id,
        loaded=entry is not None,
        # 未加载原因（v1.32）：让界面从「未加载」变成「为什么没加载、该怎么下手」
        load_error=deps.repos.load_error_of(repo_id),
        total_events=None, total_nodes=None,
        db_path=record.db_path, json_path=record.json_path,
        created_at=record.created_at, updated_at=record.updated_at,
    )


@router.get("/repos", response_model=RepoListResponse)
async def list_repos() -> RepoListResponse:
    """库登记列表：休眠库不打开文件，计数留空。"""
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    infos = []
    for repo_id in deps.repos.records:
        info = _repo_info(repo_id)
        entry = deps.repos.entries.get(repo_id)
        if entry is not None:
            info.total_events = await entry.event_store.total_events()
            info.total_nodes = entry.graph_store.total_nodes()
        infos.append(info)
    return RepoListResponse(repos=infos, active_repo_id=deps.repos.active_id)


@router.get("/repos/{repo_id}")
async def get_repo(repo_id: str) -> dict[str, Any]:
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    if repo_id not in deps.repos.records:
        raise HTTPException(status_code=404, detail="Repo not found")
    info = _repo_info(repo_id)
    entry = deps.repos.entries.get(repo_id)
    extra: dict[str, Any] = {}
    if entry is not None:
        info.total_events = await entry.event_store.total_events()
        info.total_nodes = entry.graph_store.total_nodes()
        extra["status_counts"] = await entry.event_store.count_by_status()
    return {**info.model_dump(), **extra}


@router.post("/repos")
async def create_repo(body: RepoCreateRequest) -> dict[str, Any]:
    """建库：managed 落书库根（<group_key>/<repo_id>/）；external 登记既有目录。"""
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    try:
        record = await deps.repos.create_repo(
            name=body.name, note=body.note, group=body.group,
            root_kind=body.root_kind, root=body.root,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    logger.info("Repo created: %s(%s, %s)", record.name, record.repo_id, record.root_kind)
    return _ok(repo_id=record.repo_id, message=f"库已创建：{record.name}")


@router.post("/repos/adopt", response_model=RepoAdoptResponse)
async def adopt_repo(body: RepoAdoptRequest):
    """**收养**既有目录（v1.32）：目录里至少有一个库文件即可登记为 external 书目。

    缺 `memory.db` 补空库（当前 schema）、缺 `graph.json` 补空图（带 `format_version`，
    并顺带尝试从 `graph_ops` 重放恢复图层）；**只补空件、绝不覆盖已存在的文件**。
    一个文件都没有 400（那是「新建」不是「收养」）；该目录已登记为某书目 409。
    """
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    try:
        info = await deps.repos.adopt_repo(
            root=body.root, name=body.name, note=body.note,
            group=body.group, adopt_missing=body.adopt_missing,
        )
    except RepoConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"收养失败：{exc}") from exc
    created = info["created"]
    created_note = (
        f"已补建 {'、'.join(created)}" if created else "未补建任何文件（目录里两文件本就齐备）"
    )
    load_error = deps.repos.load_error_of(info["repo_id"])
    return RepoAdoptResponse(
        repo_id=info["repo_id"],
        created=created,
        message=(
            f"目录已收养为外部库：{info['name']}（{info['repo_id']}）；{created_note}"
            + (f"；注意：{load_error}" if load_error else "；已加载")
        ),
    )


@router.post("/repos/rebuild", response_model=RepoRebuildResponse)
async def rebuild_repos():
    """重建 `repos/index.json` 登记表（坏索引恢复）：只扫盘重建，**不删任何数据文件**。

    注意：路由必须排在参数化路径之前（`/repos/rebuild` 不能被当成 `repo_id=rebuild`）。
    """
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    try:
        info = await deps.repos.rebuild_index()
    except ValueError as exc:  # 含坏索引锁存期间的写拒绝
        raise HTTPException(status_code=409, detail=f"登记表重建失败：{exc}") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"登记表重建失败（原件保留）：{exc}"
        ) from exc
    added = info.get("added") or []
    dropped = info.get("dropped") or []
    detail = []
    if added:
        detail.append(f"新登记 {len(added)} 个")
    if dropped:
        detail.append(f"移除失效登记 {len(dropped)} 个")
    latched = "（重建前为坏索引只读锁存态，已解除）" if info["latched_before"] else ""
    return RepoRebuildResponse(
        message=(
            f"登记表已重建：{info['repos']} 个库{latched}"
            + (f"；{'，'.join(detail)}" if detail else "")
            + "。未删除任何磁盘数据文件；新登记的库需重启服务或调用"
            " POST /repos/{id}/refresh 后加载。"
        ),
        repos=info["repos"],
        latched_before=info["latched_before"],
    )


@router.post("/repos/{repo_id}/purge", response_model=RepoPurgeResponse)
async def purge_repo(repo_id: str, note: str = ""):
    """清除书目：**先整库备份，再删库文件，最后摘登记**（外部库只摘登记）。"""
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    if repo_id not in deps.repos.records:
        raise HTTPException(status_code=404, detail=f"库不存在：{repo_id}")
    if repo_id == DEFAULT_REPO_ID:
        raise HTTPException(
            status_code=400,
            detail="默认库不可清除（默认库是现役数据根，其余库可清除）",
        )
    if deps.repos.active_id == repo_id:
        raise HTTPException(
            status_code=409, detail="活动库不可清除，请先切换活动库再清除"
        )
    try:
        info = await deps.repos.purge_repo(repo_id, note=note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"库不存在：{repo_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"清除库失败：{exc}") from exc
    return RepoPurgeResponse(message=info["message"], backup_path=info["backup_path"])


@router.put("/repos/{repo_id}")
async def update_repo(repo_id: str, body: RepoUpdateRequest) -> dict[str, Any]:
    """改库信息 / 受管开关（false = 休眠：不加载不检索不构图，文件不动）。

    v1.31：`root` = 外部库**重指向**（换目录）；受管库目录由系统管理，传 root 直接 400。
    """
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    record = deps.repos.records.get(repo_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Repo not found")
    if body.root is not None and record.root_kind != "external":
        raise HTTPException(
            status_code=400,
            detail="受管库目录由系统管理，不支持 root 重指向"
            "（只有外部库可以换目录）",
        )
    try:
        record = await deps.repos.update_repo(
            repo_id, name=body.name, note=body.note,
            group=body.group, managed=body.managed, root=body.root,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Repo not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _ok(message=f"库已更新：{record.name}")


@router.delete("/repos/{repo_id}")
async def delete_repo(repo_id: str) -> dict[str, Any]:
    """摘除登记（不删任何磁盘文件）；默认库与活动库不可摘。"""
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    try:
        await deps.repos.delete_repo(repo_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Repo not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _ok(message="库登记已摘除（磁盘文件保留）")


@router.post("/repos/{repo_id}/activate")
async def activate_repo(repo_id: str) -> dict[str, Any]:
    """切换活动库：未显式指定 repo_id 的写入目标。"""
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    try:
        await deps.repos.activate(repo_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Repo not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _ok(active_repo_id=repo_id, message="活动库已切换")


@router.post("/repos/{repo_id}/generate")
async def generate_repo(repo_id: str) -> dict[str, Any]:
    """库级联合生成知识：把该册全部待构图事件（raw/indexed）批量入队。

    「一库多文件联合管理」的落点——库内容整体（重新）生成知识图谱。
    """
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repos not initialized")
    if repo_id not in deps.repos.records:
        raise HTTPException(status_code=404, detail="Repo not found")
    entry = deps.repos.resolve(repo_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="Repo not loaded（未受管或加载失败）")
    if (
        settings.agent_mode != "pipeline"
        or not ai_state.available
        or deps.orchestrator is None
    ):
        raise HTTPException(
            status_code=409,
            detail="AI 不可用或 Agent 管线未启用，无法生成知识（纯存储不受影响）",
        )
    pending = [
        *await entry.event_store.list_by_status("raw"),
        *await entry.event_store.list_by_status("indexed"),
    ]
    for ev in pending:
        await deps.orchestrator.enqueue(
            QueueMessage(
                type="ingest",
                payload={"event_id": ev["event_id"], "repo_id": repo_id},
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
    logger.info("Repo generate: %s queued %d events", repo_id, len(pending))
    return _ok(
        repo_id=repo_id,
        queued=len(pending),
        message=f"已入队 {len(pending)} 条待构图事件（Gr → Meta 稍后完成，结果见图页与日志）",
    )


@router.post("/repos/{repo_id}/refresh", response_model=RepoRefreshResponse)
async def refresh_repo(repo_id: str):
    """显式刷新/修复一个库：重新对账源证 → 脏则落盘 → 回报统计。"""
    if deps.repos is None:
        raise HTTPException(status_code=503, detail="Repo manager not initialized")
    try:
        info = await deps.repos.refresh_repo(repo_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Repo not found: {repo_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # v1.46：`refresh_repo()` 返回的键是 **`changed`**，而响应模型要的是 **`reconcile_changed`**——
    # Pydantic 对未知键是 `extra='ignore'`，于是真值被**静默丢弃**、恒为 0（`message` 也恒为空）：
    # 「刷新修复」永远报「源证对账变更 0 条」，存储体检页同一数字也恒 0。
    info["reconcile_changed"] = int(info.pop("changed", 0) or 0)
    if not info.get("message"):
        info["message"] = (
            f"已重新对账：事件 {info.get('events', 0)} / 节点 {info.get('nodes', 0)} / "
            f"边 {info.get('edges', 0)}，源证对账变更 {info['reconcile_changed']} 条"
        )
    return RepoRefreshResponse(**info)
