"""Shell 模式命令解析器 — 词法分析 + 简单参数解析。"""

import shlex


def tokenize(text: str) -> list[str]:
    """将原始输入拆分为 token 列表，支持引号包围的字符串。"""
    try:
        return shlex.split(text)
    except ValueError:
        # 引号未闭合时退化为简单空格分割
        return text.strip().split()


def parse(line: str) -> tuple[str | None, dict]:
    """
    解析 Shell 输入行，返回 (command, kwargs)。

    >>> parse('search "Python" --type data --hops 3')
    ('search', {'query': 'Python', 'type': 'data', 'hops': '3'})
    """
    tokens = tokenize(line)
    if not tokens:
        return None, {}

    cmd = tokens[0]
    args = tokens[1:]
    kwargs: dict = {}
    positional: list[str] = []

    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("--"):
            key = token[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                kwargs[key] = args[i + 1]
                i += 2
            else:
                kwargs[key] = True
                i += 1
        elif token.startswith("-") and not token.startswith("--"):
            # 短选项 (暂不支持)
            i += 1
        else:
            positional.append(token)
            i += 1

    # 第一个位置参数作为主参数 (query, content 等)
    if positional:
        kwargs["positional"] = positional

    return cmd, kwargs
