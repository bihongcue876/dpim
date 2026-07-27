"""图构建 Agent：将 interaction/data 片段转化为知识节点和边"""

from core.models import GraphBuildOutput

# Agent system prompt — 由用户补充
SYSTEM_PROMPT = ""


async def build(
    fragments,
    context_nodes: list | None = None,
) -> GraphBuildOutput:
    """调用 LLM 生成新节点和边，支持节点合并。

    提示词待用户补充后启用完整逻辑，当前返回空输出占位。
    """
    return GraphBuildOutput()
