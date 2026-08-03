"""Cr 工具 — 中央控制 Agent：存入概括 + 检索意图分析（各一次有效 LLM 调用）。

管线模式下 Cr 的编排职责由 orchestrator 硬编码承担，
Cr 作为真实模型参与两个点：
- ingest：tool_cr_summarize —— 内容要点逐条概括（指引 In/Gr）
- search：tool_analyze_intent —— 意图分析（direct_search / graph_query / hybrid）
"""

from __future__ import annotations

from controller.prompt_loader import prompt_loader
from core.config import settings
from core.llm import gateway
from core.models import CrSummary, QueryIntent

from ._util import compact_json, truncate


async def tool_cr_summarize(raw_content: str, feedback: str = "") -> CrSummary:
    """对原文做逐条要点概括与主题方向提取，作为 In/Gr 的辅助上下文。

    受 DPIM_MAX_RAW_CONTENT 护栏约束：超长原文截断处理。
    """
    system = prompt_loader.load("cr")
    user = compact_json({
        "task": "summarize_content",
        "raw_content": truncate(raw_content, settings.max_raw_content),
        "previous_feedback": feedback or None,
        "output_schema": CrSummary.model_json_schema(),
    })
    result = await gateway.chat_structured("cr", CrSummary, system, user)
    return result


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
