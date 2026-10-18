"""Agent 管线 router：`/agent/*`（LLM 日志 / 手动补偿 / 手动图维护）。"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from core.config import settings
from core.llm import get_llm_logs
from core.models import MaintainRequest, QueueMessage
from interface import deps
from interface.deps import _ok

router = APIRouter()


@router.get("/agent/logs")
async def agent_logs(limit: int = 30, full: bool = False) -> dict[str, Any]:
    """返回最近 AI 调用日志（环形缓冲，新→旧），供前端观测 LLM 输入/输出。

    full=true 时返回完整 input/output/error（不做 2000 字符截断），供前端折叠查看。
    DPIM_AGENT_LOGS_FULL=false 时忽略 full 参数（日志含事件原文，部署环境可关闭全文防泄露）。
    """
    allow_full = full and settings.agent_logs_full
    return {"logs": get_llm_logs(limit=min(limit, 100), full=allow_full)}


@router.post("/agent/compensate")
async def agent_compensate(repo_id: str | None = None) -> dict[str, Any]:
    """手动触发补偿：把 raw/indexed 事件重新入队走 Agent 管线（处理积压事件）。

    force=true：补偿退避暂停中也可强制执行并重置失败计数。
    repo_id（v1.30）：指定库；缺省 = 活动库。
    """
    if deps.orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    payload: dict[str, Any] = {"force": True}
    if repo_id:
        payload["repo_id"] = repo_id
    await deps.orchestrator.enqueue(
        QueueMessage(
            type="compensate",
            payload=payload,
            timestamp=datetime.now(timezone.utc).timestamp(),
        )
    )
    return _ok(message="Compensation triggered")


@router.post("/agent/maintain")
async def agent_maintain(
    repo_id: str | None = None, body: MaintainRequest = MaintainRequest()
) -> dict[str, Any]:
    """手动触发图维护：扫描候选 → Gr 维护计划 → Meta 审核 → 执行。

    `mode`（v1.32，body）：`update`（默认）= 两阶段结构优化（Phase1 减碎+补缺 →
    Phase2 连线）；`compress` = 删繁就简（压缩 data 节点/合并/删僵尸）。
    **此前该端点完全不读 body**，payload 恒为 `{}` → orchestrator 的
    `payload.get("mode")` 永远是 None →「前端选 update 实际走 compress」，
    `^update` 能力只有 `^指令` 一条路可达（真缺陷修复）。
    body 可省略（缺省 mode=update），兼容只带 query 的既有调用。

    repo_id（v1.30）：指定库；缺省 = 活动库——此前该端点忽略库参数，
    多库环境下维护总是打在活动库上。

    AI 可用性不由本端点判定：入队后由 worker 处理，AI 不可用时维护任务自行跳过
    （与既有口径一致，不改）。
    """
    if deps.orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    payload: dict[str, Any] = {"mode": body.mode}
    if repo_id:
        payload["repo_id"] = repo_id
    await deps.orchestrator.enqueue(
        QueueMessage(
            type="maintain_graph",
            payload=payload,
            timestamp=datetime.now(timezone.utc).timestamp(),
        )
    )
    return _ok(message=f"Graph maintenance triggered (mode={body.mode})")
