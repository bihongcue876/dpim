"""Shell 模式测试 — parser 词法/参数解析、completions 补全、shell 控制命令与 args 构建。"""

import pytest
from prompt_toolkit.document import Document

from dpim_cli.completions import COMMANDS, DPIMCompleter
from dpim_cli.parser import parse, tokenize
from dpim_cli import shell


# ── parser.tokenize ──


def test_tokenize_plain():
    assert tokenize("search 关键词 --hops 2") == ["search", "关键词", "--hops", "2"]


def test_tokenize_quoted():
    assert tokenize('ingest "一段 带空格 的内容"') == ["ingest", "一段 带空格 的内容"]


def test_tokenize_unclosed_quote_fallback():
    """引号未闭合 → 退化为空格分割，不抛异常。"""
    assert tokenize('ingest "unclosed') == ["ingest", '"unclosed']


def test_tokenize_empty():
    assert tokenize("") == []
    assert tokenize("   ") == []


# ── parser.parse ──


def test_parse_empty_returns_none():
    assert parse("") == (None, {})


def test_parse_positional_only():
    cmd, kwargs = parse("status")
    assert cmd == "status"
    assert "positional" not in kwargs


def test_parse_kv_options():
    cmd, kwargs = parse('search "Python" --type data --hops 3')
    assert cmd == "search"
    assert kwargs["type"] == "data"
    assert kwargs["hops"] == "3"
    assert kwargs["positional"] == ["Python"]


def test_parse_flag_without_value():
    """--flag 后跟另一个选项或行尾 → 布尔 True。"""
    _, kwargs = parse("node delete n1 --force")
    assert kwargs["force"] is True


def test_parse_short_option_skipped():
    """短选项（单横线）暂不支持，跳过不报错、不进 positional。"""
    _, kwargs = parse("search word -x value")
    assert "-x" not in kwargs
    assert "-x" not in kwargs.get("positional", [])


def test_parse_multiple_positionals():
    _, kwargs = parse("event edit e1 新内容")
    assert kwargs["positional"] == ["edit", "e1", "新内容"]


# ── completions ──


def _completions(text: str) -> list[str]:
    doc = Document(text, len(text))
    return [c.text for c in DPIMCompleter().get_completions(doc, None)]


def test_complete_command_prefix():
    assert "status" in _completions("sta")
    assert "search" in _completions("sea")


def test_complete_all_commands_on_empty():
    result = _completions("")
    for cmd in ("status", "ingest", "search", "feedback"):
        assert cmd in result


def test_complete_subcommand_event():
    """event 后空格 → 子命令补全。"""
    result = _completions("event ")
    for sc in ("view", "edit", "retry", "skip", "unskip", "delete"):
        assert sc in result


def test_complete_subcommand_prefix_filtered():
    """输入前缀 → 只补匹配的子命令。"""
    assert _completions("event v") == ["view"]
    assert set(_completions("node e")) == {"edit"}


def test_complete_node_create_options():
    """复合键：node create 后给 create 专属选项（含 --title，不含 --force）。"""
    result = _completions("node create ")
    assert "--title" in result
    assert "--force" not in result


def test_complete_status_no_noise():
    """status 无选项 → 空补全。"""
    assert _completions("status ") == []


def test_complete_subcommand_node():
    result = _completions("node ")
    for sc in ("view", "create", "edit", "delete"):
        assert sc in result


def test_complete_options_for_search():
    result = _completions("search kw ")
    assert "--type" in result
    assert "--hops" in result


def test_complete_type_values():
    result = _completions("search kw --type ")
    assert "interaction" in result
    assert "data" in result


def test_complete_format_values():
    result = _completions("format ")
    assert "json" in result and "table" in result and "yaml" in result


def test_commands_list_covers_business():
    """补全命令表覆盖全部业务命令。"""
    for cmd in ("status", "state-key", "ingest", "events", "event", "nodes", "node",
                "edge", "search", "feedback", "config", "graph"):
        assert cmd in COMMANDS


# ── shell 控制命令 ──


class FakeSession:
    def __init__(self, items=None):
        self._items = items or []

    @property
    def history(self):
        class H:
            @staticmethod
            def get_strings():
                return self._items

        return H


@pytest.mark.parametrize("tok", ["quit", "exit", "\\q"])
def test_shell_quit_returns_true(tok):
    assert shell._handle_shell_commands(tok, FakeSession(), False) is True


def test_shell_help_returns_dict():
    assert shell._handle_shell_commands("help", FakeSession(), False) == {}


def test_shell_format_switch():
    result = shell._handle_shell_commands("format json", FakeSession(), False)
    assert result == {"format": "json"}


def test_shell_format_invalid():
    assert shell._handle_shell_commands("format xml", FakeSession(), False) == {}


def test_shell_timing_toggle():
    assert shell._handle_shell_commands("timing on", FakeSession(), False) == {"timing": True}
    assert shell._handle_shell_commands("timing off", FakeSession(), False) == {"timing": False}


def test_shell_unknown_passthrough():
    """非控制命令返回 None，交由业务执行。"""
    assert shell._handle_shell_commands("search kw", FakeSession(), False) is None


# ── _resolve_handler ──


def test_resolve_handler_all_commands():
    mapping = {
        "status": "cmd_status", "state-key": "cmd_state_key",
        "ingest": "cmd_ingest", "events": "cmd_events", "event": "cmd_event",
        "nodes": "cmd_nodes", "node": "cmd_node", "edge": "cmd_edge",
        "search": "cmd_search", "feedback": "cmd_feedback",
        "config": "cmd_config", "graph": "cmd_graph_clear",
    }
    for cmd, fn in mapping.items():
        assert shell._resolve_handler(cmd) == fn
        assert hasattr(shell.cmd_mod, fn), f"commands.{fn} 不存在"


def test_resolve_handler_unknown():
    assert shell._resolve_handler("nope") == ""


# ── _build_args ──


def test_build_args_ingest():
    args = shell._build_args("ingest", {"positional": ["内容"], "type": "data"}, "table", "u")
    assert args.content == "内容"
    assert args.type == "data"


def test_build_args_search_defaults():
    args = shell._build_args("search", {"positional": ["q"]}, "json", "u")
    assert args.query == "q"
    assert args.type == "all"
    assert args.hops == 2
    assert args.limit == 20
    assert args.offset == 0


def test_build_args_event_action_and_content():
    args = shell._build_args(
        "event", {"action": "edit", "positional": ["e1", "新内容"]}, "table", "u",
    )
    assert args.event_id == "e1"
    assert args.action == "edit"
    assert args.content == "新内容"


def test_build_args_node():
    args = shell._build_args(
        "node",
        {"positional": ["n1"], "title": "t", "force": "true", "type": "data"},
        "table", "u",
    )
    assert args.node_id == "n1"
    assert args.title == "t"
    assert args.force is True


def test_build_args_feedback_positional():
    args = shell._build_args("feedback", {"positional": ["n1"], "accept": "true"}, "table", "u")
    assert args.result_id == "n1"
    assert args.accept is True


def test_build_args_config_set():
    args = shell._build_args("config", {"action": "set", "positional": ["k", "v"]}, "table", "u")
    assert args.action == "set"
    assert args.key == "k"
    assert args.value == "v"


# ── _execute（子命令改道 + 分发） ──


def test_execute_routes_event_action(monkeypatch):
    """Shell: event edit e1 内容 → action=edit 传给 cmd_event。"""
    got = {}

    def fake_handler(args):
        got["event_id"] = args.event_id
        got["action"] = args.action
        got["content"] = args.content

    monkeypatch.setattr(shell.cmd_mod, "cmd_event", fake_handler)
    shell._execute("event edit e1 新内容", "table", "http://u")
    assert got == {"event_id": "e1", "action": "edit", "content": "新内容"}


def test_execute_routes_search(monkeypatch):
    got = {}

    def fake_handler(args):
        got["query"] = args.query
        got["hops"] = args.hops

    monkeypatch.setattr(shell.cmd_mod, "cmd_search", fake_handler)
    shell._execute('search "双区记忆" --hops 3', "table", "http://u")
    assert got == {"query": "双区记忆", "hops": 3}


def test_execute_unknown_command_prints_hint(capsys):
    shell._execute("nosuchcmd", "table", "http://u")
    assert "未知命令" in capsys.readouterr().out


def test_execute_shell_control_not_dispatched(monkeypatch):
    """shell 控制命令（如 help）不进入业务分发。"""
    called = []

    def fake_handler(args):
        called.append(args)

    monkeypatch.setattr(shell.cmd_mod, "cmd_status", fake_handler)
    shell._execute("status", "table", "http://u")
    assert len(called) == 1
    # 控制命令被 _handle_shell_commands 在 run_shell 层拦截，_execute 收到时跳过
    shell._execute("help", "table", "http://u")
    assert len(called) == 1
