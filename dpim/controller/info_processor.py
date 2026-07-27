"""信息处理 Agent：将 raw_content 分类提取为 interaction/data/source 片段"""

from core.models import InformationFragment

# Agent system prompt — 由用户补充
SYSTEM_PROMPT = ""


async def process(
    raw_content: str, existing_titles: list[str] | None = None,
) -> InformationFragment:
    """调用 LLM 对 raw_content 分类提取，返回结构化片段。

    提示词待用户补充后启用完整逻辑，当前返回空片段占位。
    """
    return InformationFragment()
