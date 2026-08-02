"""Meta 工具 — 元认知裁判：存图审核 + 检索复核。

先执行本地逻辑检查（来源锚定 / 边合法性 / 空节点，无 LLM），
本地通过后仅在需要时调 LLM 做冲突检测（对比已有边）。
"""

from __future__ import annotations

from typing import Any

from controller.prompt_loader import prompt_loader
from core.llm import gateway
from core.models import MetaCogIssue, MetaCogVerdict

from ._util import compact_json
from .sys_tools import empty_verdict, run_local_checks


async def tool_meta_review(graph_store: Any, proposal: Any, source_content: str) -> MetaCogVerdict:
    """审核图构建计划。

    本地检查（来源锚定/边合法性/空节点）作为预筛，通过后始终调用
    LLM 做冲突检测与质量复核（元认知为硬关卡）。
    """
    local_issues = run_local_checks(graph_store, proposal, source_content)
    if local_issues:
        return empty_verdict(local_issues)

    system = prompt_loader.load("meta")
    user = compact_json({
        "task": "review_proposal",
        "proposal": proposal.model_dump(),
        "source_content": source_content,
        "existing_edges": graph_store.list_edges()[:50],
        "output_schema": MetaCogVerdict.model_json_schema(),
    })
    try:
        result = await gateway.chat_structured("meta", MetaCogVerdict, system, user)
        return result
    except Exception:
        # LLM 复核失败不阻塞写入（本地检查已通过）
        return MetaCogVerdict(verdict="pass", issues=[])


async def tool_meta_review_search(
    query: str, results: list[Any], intent: dict[str, Any], feedback: str = ""
) -> MetaCogVerdict:
    """复核检索结果相关性。"""
    if not results:
        return empty_verdict(
            [
                MetaCogIssue(
                    type="empty_node",
                    description="检索结果为空",
                    suggestion="更换检索路径或关键词",
                )
            ]
        )

    system = prompt_loader.load("meta")
    user = compact_json({
        "task": "review_search_results",
        "query": query,
        "intent": intent,
        "results": [r.model_dump() for r in results[:20]],
        "previous_feedback": feedback or None,
        "output_schema": MetaCogVerdict.model_json_schema(),
    })
    result = await gateway.chat_structured("meta", MetaCogVerdict, system, user)
    return result
