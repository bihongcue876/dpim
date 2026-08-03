"""工具层共用小工具。"""

from __future__ import annotations

import json
from typing import Any


def compact_json(obj: Any) -> str:
    """压缩 JSON 序列化（保留中文）。"""
    return json.dumps(obj, ensure_ascii=False)


def issues_text(issues: list[Any]) -> str:
    """将 Meta issues 转为一句话反馈文本，注入下一轮重试上下文。"""
    return "; ".join(
        f"{i.type}: {i.suggestion or i.description}" for i in issues
    )


def truncate(text: str, limit: int) -> str:
    """上下文护栏：超限截断并附注，防止单次 LLM 调用输入过大。"""
    if limit and len(text) > limit:
        return text[:limit] + f"\n[内容超长，仅保留前 {limit} 字]"
    return text
