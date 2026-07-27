"""Tab 自动补全 — 为 prompt_toolkit 提供命令/参数/值补全。"""

from prompt_toolkit.completion import Completer, Completion


COMMANDS = [
    "status", "state-key",
    "ingest", "events", "event",
    "nodes", "node",
    "edge",
    "search", "feedback",
    "config",
    "graph",
    "help", "quit", "exit",
    "format", "timing", "clear", "history",
]

SUB_COMMANDS = {
    "event": ["view", "edit", "retry", "skip", "unskip", "delete"],
    "node": ["view", "create", "edit", "delete"],
    "edge": ["create", "delete"],
    "config": ["set"],
    "graph": ["clear"],
    "format": ["table", "json", "yaml"],
    "timing": ["on", "off"],
}

OPTIONS = {
    "ingest": ["--type"],
    "events": ["--type", "--status", "--limit", "--offset"],
    "event": ["--event"],
    "nodes": ["--type", "--limit", "--offset"],
    "node": ["--title", "--content", "--type", "--event", "--force"],
    "edge": ["--source", "--target", "--relation", "--event"],
    "search": ["--type", "--hops", "--limit", "--offset", "--format"],
    "feedback": ["--accept", "--reject"],
    "config": ["--config"],
    "node create": ["--title", "--content", "--type", "--event"],
    "edge create": ["--source", "--target", "--relation", "--event"],
    "edge delete": ["--source", "--target"],
}

TYPE_VALUES = ["all", "interaction", "data", "system", "source"]
STATUS_VALUES = ["pending", "valid", "invalid"]
BOOL_VALUES = ["on", "off"]


class DPIMCompleter(Completer):
    """智能命令补全器。"""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        tokens = text.split()
        cursor_at_end = not text or text[-1] == " "

        if not tokens or (len(tokens) == 1 and not cursor_at_end):
            # 补全命令名
            word = tokens[0] if tokens else ""
            for cmd in COMMANDS:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(word))
            return

        cmd = tokens[0]
        last_token = tokens[-1] if tokens else ""

        if cursor_at_end:
            # 用户刚输入空格，准备输入下一个参数
            if cmd == "event" and len(tokens) >= 2:
                # 子命令补全
                sub = tokens[1] if len(tokens) > 1 else ""
                for sc in SUB_COMMANDS.get("event", []):
                    yield Completion(sc)
            elif cmd == "node" and len(tokens) >= 2:
                sub = tokens[1] if len(tokens) > 1 else ""
                for sc in SUB_COMMANDS.get("node", []):
                    yield Completion(sc)
            elif cmd == "edge" and len(tokens) >= 2:
                sub = tokens[1] if len(tokens) > 1 else ""
                for sc in SUB_COMMANDS.get("edge", []):
                    yield Completion(sc)
            elif cmd in ("format", "timing"):
                for v in SUB_COMMANDS.get(cmd, []):
                    yield Completion(v)
            else:
                # 补全选项
                opts = OPTIONS.get(cmd, [])
                for o in opts:
                    yield Completion(o)
        else:
            # 选项值补全
            if last_token in ("--type", "--type="):
                for v in TYPE_VALUES:
                    yield Completion(v)
            elif last_token in ("--status", "--status="):
                for v in STATUS_VALUES:
                    yield Completion(v)
            elif last_token in ("--color", "--color="):
                for v in BOOL_VALUES:
                    yield Completion(v)
