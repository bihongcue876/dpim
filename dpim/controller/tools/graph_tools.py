"""Gr 工具 — 图对接 Agent：存图计划生成（一次有效 LLM 调用）。"""

from __future__ import annotations

from typing import Any

from controller.prompt_loader import prompt_loader
from core.llm import gateway
from core.models import AnnotatedChunks, GraphBuildOutput

from ._util import compact_json


async def tool_graph_propose(
    chunks: AnnotatedChunks,
    similar_nodes: list[Any],
    feedback: str = "",
    prior_context: str = "",
    event_id: str = "",
) -> GraphBuildOutput:
    """根据信息分块与已有近似节点，生成图构建计划。

    单次调用打包全部上下文（chunks + 瘦身后的 similar_nodes + 上一轮反馈 + Cr 要点 + Schema）。
    similar_nodes 只传摘要字段，避免全量 content 撑爆上下文。
    """
    system = prompt_loader.load("gr")
    user = compact_json({
        "task": "propose_graph",
        "event_id": event_id,
        "chunks": [c.model_dump() for c in chunks.chunks],
        "similar_nodes": [
            {
                "node_id": n.node_id,
                "title": n.title,
                "node_type": n.node_type.value,
                "confidence": n.confidence,
                "snippet": (n.content or "")[:100],
            }
            for n in similar_nodes
        ],
        "prior_context": prior_context or None,
        "previous_feedback": feedback or None,
        "output_schema": GraphBuildOutput.model_json_schema(),
    })
    result = await gateway.chat_structured("gr", GraphBuildOutput, system, user)
    return result


async def tool_maintain_propose(
    graph_store: Any, candidates: dict, feedback: str = ""
) -> Any:
    """图维护计划（任务二 maintain_graph）：基于扫描候选做合并/删除/修改决策。

    单次调用打包全部上下文（candidates + 图统计 + 上一轮反馈 + Schema）。
    保守优先：不确定就不动，空计划合法。
    """
    from core.models import GraphMaintenancePlan

    system = prompt_loader.load("gr")
    user = compact_json({
        "task": "maintain_graph",
        "candidates": candidates,
        "previous_feedback": feedback or None,
        "output_schema": GraphMaintenancePlan.model_json_schema(),
    })
    result = await gateway.chat_structured("gr", GraphMaintenancePlan, system, user)
    return result
