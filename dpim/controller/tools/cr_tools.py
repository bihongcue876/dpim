"""Cr 工具 — 中央控制 Agent：检索意图分析（一次有效 LLM 调用）。

管线模式下 Cr 的编排职责由 orchestrator 硬编码承担，
仅检索流程需要 Cr 做意图分析（direct_search / graph_query / hybrid）。
"""

from __future__ import annotations

from controller.prompt_loader import prompt_loader
from core.llm import gateway
from core.models import QueryIntent

from ._util import compact_json


async def tool_analyze_intent(query: str, feedback: str = "") -> QueryIntent:
    """分析检索意图，选择检索路径。"""
    system = prompt_loader.load("cr")
    user = compact_json({
        "task": "analyze_search_intent",
        "query": query,
        "previous_feedback": feedback or None,
        "output_schema": QueryIntent.model_json_schema(),
    })
    result = await gateway.chat_structured("cr", QueryIntent, system, user)
    return result
