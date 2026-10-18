"""Tab 自动补全 — 为 prompt_toolkit 提供命令/参数/值补全。"""

from prompt_toolkit.completion import Completer, Completion


COMMANDS = [
    "status", "state-key",
    "ingest", "events", "event",
    "nodes", "node",
    "edge", "edges",
    "search", "feedback",
    "config",
    "graph",
    "repo", "maintenance", "logs", "trash", "agent",
    "help", "quit", "exit",
    "format", "timing", "clear", "history",
]

SUB_COMMANDS = {
    "event": ["view", "edit", "retry", "skip", "unskip", "delete"],
    "node": ["view", "create", "edit", "delete"],
    "edge": ["create", "delete"],
    "config": ["list", "set", "probe"],
    "graph": ["clear"],
    "repo": ["list", "show", "create", "update", "delete", "activate",
             "refresh", "generate", "adopt", "rebuild", "purge"],
    "maintenance": ["backup", "backups", "verify", "ops", "checkpoint"],
    "trash": ["list", "restore"],
    "agent": ["logs", "compensate", "maintain"],
    "format": ["table", "json", "yaml"],
    "timing": ["on", "off"],
}

# 库作用域（v1.29/v1.30）：读命令单库 --repo；列表/检索类还可 --repos 联查
_SCOPE_SINGLE = ["--repo"]
_SCOPE_JOINT = ["--repo", "--repos"]

OPTIONS = {
    "ingest": ["--type", *_SCOPE_SINGLE],
    "events": ["--type", "--status", "--limit", "--offset", *_SCOPE_JOINT],
    "event": ["--event", *_SCOPE_SINGLE],
    "nodes": ["--type", "--limit", "--offset", *_SCOPE_JOINT],
    "node": ["--title", "--content", "--type", "--event", "--force", *_SCOPE_SINGLE],
    "edge": ["--source", "--target", "--relation", "--event"],
    "edges": ["--node", "--source", "--target", "--relation", "--limit", "--offset",
              *_SCOPE_JOINT],
    "search": ["--type", "--hops", "--limit", "--offset", "--format", *_SCOPE_JOINT],
    "feedback": ["--accept", "--reject", *_SCOPE_SINGLE],
    "config": ["--config", "--base-url", "--api-key"],
    "repo": ["--name", "--note", "--group", "--root", "--kind", "--managed",
             "--no-missing", "--yes"],
    "maintenance": ["--note", "--limit", "--offset", *_SCOPE_SINGLE],
    "logs": ["--kind", "--date", "--level", "--keyword", "--tail"],
    "trash": ["--kind", *_SCOPE_SINGLE],
    "agent": ["--limit", "--full", "--mode", *_SCOPE_SINGLE],
    "node create": ["--title", "--content", "--type", "--event"],
    "edge create": ["--source", "--target", "--relation", "--event"],
    "edge delete": ["--source", "--target"],
}

TYPE_VALUES = ["all", "interaction", "data", "system", "source"]
STATUS_VALUES = ["raw", "indexed", "linked", "failed", "skipped"]
BOOL_VALUES = ["on", "off"]

# 选项 → 候选值
OPTION_VALUES = {
    "--type": TYPE_VALUES,
    "--status": STATUS_VALUES,
    "--color": BOOL_VALUES,
    "--kind": ["managed", "external", "event", "node", "backend", "frontend"],
    "--managed": ["true", "false"],
    "--mode": ["update", "compress"],
}


class DPIMCompleter(Completer):
    """智能命令补全器（按光标位置区分：命令名 / 子命令 / 选项名 / 选项值）。"""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        tokens = text.split()
        cursor_at_end = not text or text[-1] == " "

        # ── 1) 命令名补全（正在输入第一个词）──
        if not tokens or (len(tokens) == 1 and not cursor_at_end):
            word = tokens[0] if tokens else ""
            for cmd in COMMANDS:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(word))
            return

        cmd = tokens[0]

        # ── 2) 子命令补全（复合命令的第二个词位置）──
        subs = SUB_COMMANDS.get(cmd, [])
        if subs and cmd not in ("format", "timing"):
            if len(tokens) == 1 and cursor_at_end:
                for sc in subs:
                    yield Completion(sc)
                return
            if len(tokens) == 2 and not cursor_at_end:
                word = tokens[1]
                for sc in subs:
                    if sc.startswith(word):
                        yield Completion(sc, start_position=-len(word))
                return

        # ── 确定待补全词与其前一词 ──
        if cursor_at_end:
            word, prev = "", tokens[-1]
        else:
            word, prev = tokens[-1], (tokens[-2] if len(tokens) >= 2 else "")

        # ── 3) 选项值补全（prev 是已知取值选项）──
        values = OPTION_VALUES.get(prev, [])
        if values:
            for v in values:
                if v.startswith(word):
                    yield Completion(v, start_position=-len(word))
            return

        # ── 4) format / timing 的值 ──
        if cmd in ("format", "timing"):
            if cursor_at_end:
                for v in SUB_COMMANDS.get(cmd, []):
                    yield Completion(v)
            return

        # ── 5) 选项名补全（正在输入 --xx 或空格后列出全部）──
        opts = self._options_for(cmd, tokens)
        for o in opts:
            if o.startswith(word):
                yield Completion(o, start_position=-len(word))

    @staticmethod
    def _options_for(cmd: str, tokens: list[str]) -> list[str]:
        """选项集合：复合键（如 'node create'）优先，回退单命令。"""
        if len(tokens) >= 2 and f"{cmd} {tokens[1]}" in OPTIONS:
            return OPTIONS[f"{cmd} {tokens[1]}"]
        return OPTIONS.get(cmd, [])
