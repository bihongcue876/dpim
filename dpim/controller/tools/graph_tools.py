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
) -> GraphBuildOutput:
    """根据信息分块与已有近似节点，生成图构建计划。

    单次调用打包全部上下文（chunks + similar_nodes + 上一轮反馈 + Schema）。
    """
    system = prompt_loader.load("gr")
    user = compact_json({
        "task": "propose_graph",
        "chunks": [c.model_dump() for c in chunks.chunks],
        "similar_nodes": [n.model_dump() for n in similar_nodes],
        "previous_feedback": feedback or None,
        "output_schema": GraphBuildOutput.model_json_schema(),
    })
    result = await gateway.chat_structured("gr", GraphBuildOutput, system, user)
    return result
