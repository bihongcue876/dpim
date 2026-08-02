"""In 工具 — 信息管理 Agent：内容分拣与标注（一次有效 LLM 调用）。"""

from __future__ import annotations

from controller.prompt_loader import prompt_loader
from core.llm import gateway
from core.models import AnnotatedChunks

from ._util import compact_json


async def tool_info_split(raw_content: str, feedback: str = "") -> AnnotatedChunks:
    """对原文进行语义分块、类型标注与标题拟定。

    单次调用打包全部上下文（raw_content + 上一轮反馈 + 输出 Schema）。
    输出 AnnotatedChunks：每个分块必须是原文连续子串。
    """
    system = prompt_loader.load("in")
    user = compact_json({
        "task": "split_and_label",
        "raw_content": raw_content,
        "previous_feedback": feedback or None,
        "output_schema": AnnotatedChunks.model_json_schema(),
    })
    result = await gateway.chat_structured("in", AnnotatedChunks, system, user)
    return result
