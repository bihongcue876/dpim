"""元认知裁判：审查图构建 Agent 输出，决定通过或驳回"""

from core.models import GraphBuildOutput, MetaCogVerdict

# Judge system prompt — 由用户补充
SYSTEM_PROMPT = ""


async def judge(build_output: GraphBuildOutput, source_event: dict) -> MetaCogVerdict:
    """审查图构建输出，按规则检查来源锚定、边合法性、冲突和空节点。

    提示词待用户补充后启用完整逻辑，当前返回通过占位。
    """
    return MetaCogVerdict(verdict="pass", issues=[])
