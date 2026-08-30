"""对话指令识别与解析：信息传入框输入运维指令，不落库为事件。

语法（v1.21，仅此一种形式；其余一律视为普通文本正常落库）：
    ^动词 [参数...]（英文动词、空格分隔、大小写不敏感；全角 ＾ ｜ 归一化）

- 语义层（需 AI 可用 + 管线启用）：
  ^compress [node_id] —— 图维护（压缩）轮：扫描 → Gr 计划 → Meta 审核 → 执行；
    保守语义：全图足够简练则空计划、不动任何东西；可带节点 ID 限定范围。
- 确定层（无 LLM，同步执行）：
  ^merge <target_id> <source_id> —— 合并节点（源证并集 + 内容去重合并不丢失）
  ^delete <node_id> —— 删除节点（删除保护 + system 保护）
  ^data <内容> / ^interaction <内容> / ^source <内容>
    —— 显式类型存入线层（指令前缀不落库；纯存储，AI 不可用也可用）
  ^node system <标题> | <内容> —— 手工系统节点直建（无源证要求）
- ^help —— 返回全部指令用法说明。

未识别的形式（/ 前缀、中文指令词、冒号分隔、未知 ^词、裸 ^）→
不是指令，parse_command 返回 None，按普通文本写入事件。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ParsedCommand:
    """解析结果。kind 见 _VERBS / _STORE_WORDS；hints 为用法错误提示。"""

    kind: str
    # store
    event_type: str = ""
    content: str = ""
    # compress（范围限定，可选）
    scope: str = ""
    # merge
    target_id: str = ""
    source_id: str = ""
    # delete / node
    node_id: str = ""
    title: str = ""
    # 用法错误的补充提示
    hints: list[str] = field(default_factory=list)


# 指令词（小写）→ 动作 kind
_VERBS: dict[str, str] = {
    "compress": "compress",
    "merge": "merge",
    "delete": "delete",
    "node": "node",
    "help": "help",
}

# 存储类指令词 → 事件类型
_STORE_WORDS: dict[str, str] = {
    "data": "data",
    "interaction": "interaction",
    "source": "source",
}


def parse_command(content: str) -> ParsedCommand | None:
    """解析 ^指令；非指令（含被 ban 的形式）返回 None → 普通文本落库。

    严格空格分隔：冒号不是分隔符（^data: 内容 不是指令）；
    已识别指令但参数不合法 → kind 照常返回 + hints（调用方提示且不落库）。
    """
    text = (content or "").strip().replace("＾", "^").replace("｜", "|")
    if not text.startswith("^"):
        return None
    # 指令词 = ^ 后到首个空白；严格空格分隔
    parts = text[1:].split(None, 1)
    if not parts:
        return None  # 裸 ^ 不是指令
    word = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if word in _STORE_WORDS:
        if not rest:
            return ParsedCommand(
                kind="store", event_type=_STORE_WORDS[word],
                hints=[f"缺少内容：^{word} <内容>"],
            )
        return ParsedCommand(kind="store", event_type=_STORE_WORDS[word], content=rest)

    if word not in _VERBS:
        return None  # 未识别的 ^词 → 普通文本

    kind = _VERBS[word]
    if kind == "help":
        return ParsedCommand(kind="help")
    if kind == "compress":
        return ParsedCommand(kind="compress", scope=rest.split()[0] if rest else "")
    if kind == "delete":
        if not rest:
            return ParsedCommand(kind="delete", hints=["缺少节点 ID：^delete <node_id>"])
        return ParsedCommand(kind="delete", node_id=rest.split()[0])
    if kind == "merge":
        ids = rest.split()
        if len(ids) != 2:
            return ParsedCommand(
                kind="merge",
                hints=["参数应为两个节点 ID：^merge <target_id> <source_id>"],
            )
        return ParsedCommand(kind="merge", target_id=ids[0], source_id=ids[1])

    # node：^node system <标题> | <内容>（严格空格）
    m = re.match(r"^system(\s+|$)", rest)
    if not m:
        return ParsedCommand(
            kind="node",
            hints=["目前仅支持系统节点：^node system <标题> | <内容>"],
        )
    payload = rest[m.end():]
    segs = [s.strip() for s in payload.split("|", 1)]
    title = segs[0] if segs and segs[0] else ""
    content_seg = segs[1].strip() if len(segs) > 1 else ""
    if not title or not content_seg:
        return ParsedCommand(
            kind="node",
            hints=["格式：^node system <标题> | <内容>（标题与内容均必填）"],
        )
    return ParsedCommand(kind="node", title=title, content=content_seg)


def usage_text() -> str:
    """全部指令的用法说明（^help / 帮助时返回给用户）。"""
    return (
        "支持的指令（仅 ^ 前缀 + 英文，空格分隔；输入 ^ 可自动弹出候选）：\n"
        "  ^compress [节点ID] —— 触发图压缩维护（需 AI；全图足够简练则不做任何改动）\n"
        "  ^merge <目标ID> <源ID> —— 合并节点（内容合并不丢失）\n"
        "  ^delete <节点ID> —— 删除节点（受删除保护与 system 保护）\n"
        "  ^data <内容> —— 按 data 类型存入\n"
        "  ^interaction <内容> —— 按 interaction 类型存入\n"
        "  ^source <内容> —— 按 source 类型存入（仅存储不构图）\n"
        "  ^node system <标题> | <内容> —— 手工创建系统节点\n"
        "  ^help —— 查看本说明"
    )
