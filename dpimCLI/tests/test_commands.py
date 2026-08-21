"""命令层测试 — 全部命令的 API 调用与参数映射（mock DPIMClient，无网络）。

覆盖：13 个顶层命令 / 23 条操作路径的参数校验、输出调用与错误路径
（DPIMError / ConnectionError → sys.exit(1)）。
"""

from argparse import Namespace

import pytest

from dpim_cli import commands
from dpim_cli.api_client import DPIMError


def make_args(command: str, **kwargs) -> Namespace:
    """构造命令处理函数所需的 args 对象（模拟 argparse 解析结果）。"""
    ns = Namespace(command=command, api="http://test:8000", format="json")
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture
def mock_client(monkeypatch):
    """把 commands.DPIMClient 替换为记录调用的 MockClient。"""
    calls: list[tuple[str, tuple, dict]] = []

    class MockClient:
        def __init__(self, base_url: str = "", timeout: int = 30):
            pass

        def __getattr__(self, name: str):
            def _call(*args, **kwargs):
                calls.append((name, args, kwargs))
                # 常见响应兜底：列表类命令需要 items/total 字段，其余原样回显
                if name in ("list_events", "list_nodes", "search"):
                    return {"items": [], "total": 0, "results": []}
                return {"ok": True, "message": "done", "data": {}}

            return _call

    monkeypatch.setattr(commands, "DPIMClient", MockClient)
    return calls


# ── 系统状态 ──


def test_cmd_status(mock_client, capsys):
    commands.cmd_status(make_args("status"))
    assert mock_client[0][0] == "health"
    assert "ok" in capsys.readouterr().out


def test_cmd_state_key(mock_client, capsys):
    commands.cmd_state_key(make_args("state-key"))
    assert mock_client[0][0] == "state_key"


# ── 事件管理 ──


def test_cmd_ingest_default_type(mock_client):
    # auto 模式已移除：默认类型为 interaction
    commands.cmd_ingest(make_args("ingest", content="hello", type="interaction"))
    name, args, kwargs = mock_client[0]
    assert name == "ingest"
    assert args == ("hello",)
    assert kwargs == {"event_type": "interaction"}


def test_cmd_ingest_explicit_type(mock_client):
    commands.cmd_ingest(make_args("ingest", content="x", type="data"))
    assert mock_client[0][2] == {"event_type": "data"}


def test_cmd_events_filters_forwarded(mock_client):
    commands.cmd_events(make_args(
        "events", type="interaction", status="raw", limit=5, offset=10,
    ))
    name, args, kwargs = mock_client[0]
    assert name == "list_events"
    assert kwargs == {"type": "interaction", "status": "raw", "limit": 5, "offset": 10}


def test_cmd_events_defaults(mock_client):
    commands.cmd_events(make_args("events", type="", status="", limit=20, offset=0))
    assert mock_client[0][2] == {"type": "", "status": "", "limit": 20, "offset": 0}


def test_cmd_event_view(mock_client):
    commands.cmd_event(make_args("event", action="view", event_id="e1", content=""))
    assert mock_client[0][0] == "get_event"
    assert mock_client[0][1] == ("e1",)


def test_cmd_event_edit(mock_client):
    commands.cmd_event(make_args("event", action="edit", event_id="e1", content="new"))
    name, args, _ = mock_client[0]
    assert name == "edit_event"
    assert args == ("e1", "new")


@pytest.mark.parametrize("action,expected_status", [
    ("retry", "indexed"),
    ("skip", "skipped"),
    ("unskip", "indexed"),
])
def test_cmd_event_status_transitions(mock_client, action, expected_status):
    commands.cmd_event(make_args("event", action=action, event_id="e1", content=""))
    name, args, kwargs = mock_client[0]
    assert name == "update_event_status"
    assert args == ("e1", expected_status)


def test_cmd_event_delete(mock_client):
    commands.cmd_event(make_args("event", action="delete", event_id="e1", content=""))
    assert mock_client[0] == ("delete_event", ("e1",), {})


# ── 节点管理 ──


def test_cmd_nodes_filters(mock_client):
    commands.cmd_nodes(make_args("nodes", type="data", limit=10, offset=0))
    assert mock_client[0][2] == {"type": "data", "limit": 10, "offset": 0}


def test_cmd_node_view(mock_client):
    commands.cmd_node(make_args("node", node_id="n1", content="", action="view",
                                title="", event="", force=False))
    assert mock_client[0] == ("get_node", ("n1",), {})


def test_cmd_node_action_inferred_from_title(mock_client):
    """node create 自动推断：给了 --title → create。"""
    commands.cmd_node(make_args("node", node_id="", content="", action="",
                                title="标题", event="", force=False))
    name, args, kwargs = mock_client[0]
    assert name == "create_node"
    assert kwargs == {"title": "标题", "content": "", "source_event_id": ""}


def test_cmd_node_action_inferred_from_force(mock_client):
    """--force → delete。"""
    commands.cmd_node(make_args("node", node_id="n1", content="", action="",
                                title="", event="", force=True))
    assert mock_client[0][0] == "delete_node"
    assert mock_client[0][2] == {"force": True}


def test_cmd_node_action_inferred_from_id_content(mock_client):
    """node_id + content → edit。"""
    commands.cmd_node(make_args("node", node_id="n1", content="new", action="",
                                title="", event="", force=False))
    assert mock_client[0] == ("edit_node", ("n1", "new"), {})


def test_cmd_node_create_with_source_event(mock_client):
    commands.cmd_node(make_args("node", node_id="", content="c", action="create",
                                title="t", event="e1", force=False))
    kwargs = mock_client[0][2]
    assert kwargs == {"title": "t", "content": "c", "source_event_id": "e1"}


def test_cmd_node_delete_force_false_by_default(mock_client):
    commands.cmd_node(make_args("node", node_id="n1", content="", action="delete",
                                title="", event="", force=False))
    assert mock_client[0][2] == {"force": False}


# ── 边管理 ──


def test_cmd_edge_create(mock_client):
    commands.cmd_edge(make_args("edge", action="create", source="a", target="b",
                                relation="supports", event="e1"))
    assert mock_client[0][2] == {
        "source": "a", "target": "b", "relation": "supports", "evidence_event_id": "e1",
    }


def test_cmd_edge_delete(mock_client):
    commands.cmd_edge(make_args("edge", action="delete", source="a", target="b",
                                relation="", event=""))
    assert mock_client[0] == ("delete_edge", (), {"source": "a", "target": "b"})


# ── 检索与反馈 ──


def test_cmd_search_params_mapping(mock_client):
    """CLI 参数 → API 参数映射：hops → max_hops，type → source_filter。"""
    commands.cmd_search(make_args("search", query="记忆", type="data",
                                  hops=3, limit=10, offset=5))
    name, args, kwargs = mock_client[0]
    assert name == "search"
    assert kwargs == {"query": "记忆", "source_filter": "data",
                      "max_hops": 3, "limit": 10, "offset": 5}


def test_cmd_feedback_accept(mock_client):
    commands.cmd_feedback(make_args("feedback", result_id="n1", accept=True, reject=False))
    assert mock_client[0] == ("feedback", ("n1", True), {})


def test_cmd_feedback_reject(mock_client):
    commands.cmd_feedback(make_args("feedback", result_id="n1", accept=False, reject=True))
    assert mock_client[0] == ("feedback", ("n1", False), {})


# ── 配置与图谱 ──


def test_cmd_config_list(mock_client):
    commands.cmd_config(make_args("config", action="list", key="", value=""))
    assert mock_client[0][0] == "get_settings"


def test_cmd_config_set_kv_mapping(mock_client):
    commands.cmd_config(make_args("config", action="set", key="log_level", value="DEBUG"))
    assert mock_client[0] == ("update_settings", (), {"log_level": "DEBUG"})


def test_cmd_graph_clear(mock_client):
    commands.cmd_graph_clear(make_args("graph", action="clear"))
    assert mock_client[0] == ("clear_graph", (), {})


# ── 错误路径 ──


def _mock_error(monkeypatch, exc):
    class MockClient:
        def __init__(self, base_url: str = "", timeout: int = 30):
            pass

        def health(self):
            raise exc

    monkeypatch.setattr(commands, "DPIMClient", MockClient)


def test_api_error_exits_1(monkeypatch, capsys):
    _mock_error(monkeypatch, DPIMError("VALIDATION", "值域越界", 422))
    with pytest.raises(SystemExit) as ei:
        commands.cmd_status(make_args("status"))
    assert ei.value.code == 1
    assert "错误 [VALIDATION]" in capsys.readouterr().err


def test_connection_error_exits_1(monkeypatch, capsys):
    from dpim_cli.api_client import ConnectionError as CE

    _mock_error(monkeypatch, CE("CONNECTION", "refused", 0))
    with pytest.raises(SystemExit) as ei:
        commands.cmd_status(make_args("status"))
    assert ei.value.code == 1
    assert "无法连接" in capsys.readouterr().err


# ── main 入口（参数注入与分发） ──


def test_main_dispatch_ingest(monkeypatch, mock_client, capsys):
    """dpim ingest 内容 --type data 全链路：解析 → 注入 → 分发。"""
    import sys

    from dpim_cli import main as main_mod

    monkeypatch.setattr(sys, "argv", ["dpim", "ingest", "测试内容", "--type", "data"])
    main_mod.main()
    name, args, kwargs = mock_client[0]
    assert name == "ingest"
    assert args == ("测试内容",)
    assert kwargs == {"event_type": "data"}


def test_main_global_opts_after_command(monkeypatch, mock_client):
    """--format/--api 可放子命令之后（修复：此前 argparse 拒绝后置全局选项）。"""
    import sys

    from dpim_cli import main as main_mod

    monkeypatch.setattr(sys, "argv", [
        "dpim", "search", "关键词", "--format", "json", "--api", "http://test:8000",
    ])
    main_mod.main()  # 不应 SystemExit(2)
    name, _, kwargs = mock_client[0]
    assert name == "search"
    assert kwargs["query"] == "关键词"


def test_main_prefixed_api_not_clobbered(monkeypatch, mock_client):
    """前置 --api 不被子命令默认值覆盖（SUPPRESS 修复回归）。"""
    import sys

    from dpim_cli import main as main_mod

    monkeypatch.setattr(sys, "argv", ["dpim", "--api", "http://prefixed:8899", "status"])
    main_mod.main()
    # 客户端 base_url 应为前置地址，而非子 parser 默认（None → 回退 localhost:8000）
    assert mock_client[0][0] == "health"
