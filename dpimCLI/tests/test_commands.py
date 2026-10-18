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
                # 常见响应兜底：列表类命令需要各自的外层字段名，其余原样回显
                # （注意后端用的是 `repos` / `ops` / `backups` / `logs`，
                #   只有 /events、/nodes、/edges、/trash 用 `items`）
                if name in ("list_events", "list_nodes", "list_edges", "trash_list"):
                    return {"items": [], "total": 0, "results": []}
                if name == "list_repos":
                    return {"repos": [], "active_repo_id": ""}
                if name == "maintenance_ops":
                    return {"ops": [], "total": 0}
                if name == "maintenance_backups":
                    return {"backups": []}
                if name == "agent_logs":
                    return {"logs": []}
                if name == "logs":
                    return {"kind": "backend", "date": "2026-10-17", "dir": "d",
                            "files": [], "lines": [], "truncated": False}
                if name == "search":
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
    # auto 模式已移除：默认类型为 interaction；v1.39 起带库作用域（缺省空串 = 活动库）
    commands.cmd_ingest(make_args("ingest", content="hello", type="interaction"))
    name, args, kwargs = mock_client[0]
    assert name == "ingest"
    assert args == ("hello",)
    assert kwargs == {"event_type": "interaction", "repo_id": ""}


def test_cmd_ingest_explicit_type(mock_client):
    commands.cmd_ingest(make_args("ingest", content="x", type="data"))
    assert mock_client[0][2] == {"event_type": "data", "repo_id": ""}


def test_formatter_ingest_command_triggered(capsys):
    """对话指令响应（/压缩、/merge、/data: 等）：table 格式显示指令结果消息。"""
    from dpim_cli import formatter

    text = formatter.ingest_result({
        "event_id": "", "status": "skipped",
        "command_triggered": True, "message": "压缩指令已入队",
    })
    assert "指令结果" in text
    assert "压缩指令已入队" in text


def test_formatter_ingest_normal_event(capsys):
    from dpim_cli import formatter

    text = formatter.ingest_result({"event_id": "e1", "status": "indexed"})
    assert "事件已写入" in text
    assert "e1" in text


def test_cmd_events_filters_forwarded(mock_client):
    commands.cmd_events(make_args(
        "events", type="interaction", status="raw", limit=5, offset=10,
    ))
    name, args, kwargs = mock_client[0]
    assert name == "list_events"
    assert kwargs == {"type": "interaction", "status": "raw", "limit": 5, "offset": 10,
                      "repo_id": "", "repo_ids": []}


def test_cmd_events_defaults(mock_client):
    commands.cmd_events(make_args("events", type="", status="", limit=20, offset=0))
    assert mock_client[0][2] == {"type": "", "status": "", "limit": 20, "offset": 0,
                                 "repo_id": "", "repo_ids": []}


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
    assert mock_client[0][2] == {"type": "data", "limit": 10, "offset": 0,
                                 "repo_id": "", "repo_ids": []}


def test_cmd_node_view(mock_client):
    commands.cmd_node(make_args("node", node_id="n1", content="", action="view",
                                title="", event="", force=False))
    assert mock_client[0] == ("get_node", ("n1",), {"repo_id": ""})


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
                      "max_hops": 3, "limit": 10, "offset": 5, "repo_ids": []}


def test_cmd_feedback_accept(mock_client):
    commands.cmd_feedback(make_args("feedback", result_id="n1", accept=True, reject=False))
    assert mock_client[0] == ("feedback", ("n1", True), {"repo_id": ""})


def test_cmd_feedback_reject(mock_client):
    commands.cmd_feedback(make_args("feedback", result_id="n1", accept=False, reject=True))
    assert mock_client[0] == ("feedback", ("n1", False), {"repo_id": ""})


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
    assert kwargs == {"event_type": "data", "repo_id": ""}


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


# ── 库作用域（v1.29/v1.30，链 AD）─────────────────────────────────────────


def test_repo_params_drops_empty_and_joins():
    """`repo_params` 只拼非空值：空串会让后端踩 404/422（缺省语义 ≠ 空串）。"""
    from dpim_cli.api_client import repo_params

    assert repo_params() == {}
    assert repo_params("", []) == {}
    assert repo_params("rp_a") == {"repo_id": "rp_a"}
    assert repo_params(repo_ids=["rp_a", "", "rp_b"]) == {"repo_ids": "rp_a,rp_b"}
    assert repo_params("rp_a", ["rp_b"]) == {"repo_id": "rp_a", "repo_ids": "rp_b"}


def test_cmd_events_forwards_scope(mock_client):
    commands.cmd_events(make_args("events", type="", status="", limit=20, offset=0,
                                  repo="rp_a", repos="rp_b,rp_c"))
    kwargs = mock_client[0][2]
    assert kwargs["repo_id"] == "rp_a"
    assert kwargs["repo_ids"] == ["rp_b", "rp_c"]


def test_cmd_ingest_forwards_repo(mock_client):
    commands.cmd_ingest(make_args("ingest", content="x", type="data", repo="rp_a"))
    assert mock_client[0][2] == {"event_type": "data", "repo_id": "rp_a"}


def test_cmd_node_view_forwards_repo(mock_client):
    """跨库跳转必须带 repo_id，否则后端只在活动库里找 → 404。"""
    commands.cmd_node(make_args("node", node_id="n1", content="", action="view",
                                title="", event="", force=False, repo="rp_a"))
    assert mock_client[0] == ("get_node", ("n1",), {"repo_id": "rp_a"})


def test_cmd_search_forwards_repos(mock_client):
    commands.cmd_search(make_args("search", query="q", type="all", hops=2, limit=20,
                                  offset=0, repos="rp_a,rp_b"))
    assert mock_client[0][2]["repo_ids"] == ["rp_a", "rp_b"]


# ── 边列表（GET /edges，v1.37）───────────────────────────────────────────


def test_cmd_edges_forwards_filters(mock_client):
    commands.cmd_edges(make_args("edges", node="n1", source="", target="n2",
                                 relation="part_of", limit=50, offset=5,
                                 repo="", repos="rp_a"))
    name, args, kwargs = mock_client[0]
    assert name == "list_edges"
    assert kwargs == {"node_id": "n1", "source": "", "target": "n2",
                      "relation": "part_of", "limit": 50, "offset": 5,
                      "repo_id": "", "repo_ids": ["rp_a"]}


# ── 库管理（11 个端点）──────────────────────────────────────────────────


def test_cmd_repo_list(mock_client):
    commands.cmd_repo(make_args("repo", action="list"))
    assert mock_client[0][0] == "list_repos"


def test_cmd_repo_show(mock_client):
    commands.cmd_repo(make_args("repo", action="show", repo_id="rp_a"))
    assert mock_client[0] == ("get_repo", ("rp_a",), {})


def test_cmd_repo_create_maps_fields(mock_client):
    commands.cmd_repo(make_args("repo", action="create", name="新库", group="工作",
                                note="备注", root="D:/data/x", kind="external"))
    name, args, kwargs = mock_client[0]
    assert name == "create_repo"
    assert kwargs == {"name": "新库", "group": "工作", "note": "备注",
                      "root": "D:/data/x", "root_kind": "external"}


def test_cmd_repo_update_only_sends_given_fields(mock_client):
    commands.cmd_repo(make_args("repo", action="update", repo_id="rp_a", name="改",
                                note="", group="", root="", managed=None))
    assert mock_client[0] == ("update_repo", ("rp_a",), {"name": "改"})


def test_cmd_repo_update_managed_flag(mock_client):
    """--managed false → 休眠（不加载、不检索、不构图，文件不动）。"""
    commands.cmd_repo(make_args("repo", action="update", repo_id="rp_a", name="",
                                note="", group="", root="", managed="false"))
    assert mock_client[0][2] == {"managed": False}


def test_cmd_repo_update_requires_a_field(mock_client, capsys):
    with pytest.raises(SystemExit) as ei:
        commands.cmd_repo(make_args("repo", action="update", repo_id="rp_a", name="",
                                    note="", group="", root="", managed=None))
    assert ei.value.code == 1
    assert "至少给一项" in capsys.readouterr().err


def test_cmd_repo_lifecycle_actions(mock_client):
    for action, method in (("delete", "delete_repo"), ("activate", "activate_repo"),
                           ("refresh", "refresh_repo"), ("generate", "generate_repo")):
        mock_client.clear()
        commands.cmd_repo(make_args("repo", action=action, repo_id="rp_a"))
        assert mock_client[0] == (method, ("rp_a",), {})


def test_cmd_repo_adopt_defaults_to_filling_missing(mock_client):
    commands.cmd_repo(make_args("repo", action="adopt", root="D:/half", name="半损",
                                group="", no_missing=False))
    name, args, kwargs = mock_client[0]
    assert name == "adopt_repo"
    assert kwargs == {"root": "D:/half", "name": "半损", "group": "",
                      "adopt_missing": True}


def test_cmd_repo_adopt_no_missing_flag(mock_client):
    commands.cmd_repo(make_args("repo", action="adopt", root="D:/half", name="",
                                group="", no_missing=True))
    assert mock_client[0][2]["adopt_missing"] is False


def test_cmd_repo_rebuild(mock_client):
    commands.cmd_repo(make_args("repo", action="rebuild"))
    assert mock_client[0][0] == "rebuild_repos"


def test_cmd_repo_purge_requires_yes(mock_client, capsys):
    """purge 会删库文件（后端先自动备份）：没有 --yes 一律拒绝执行。"""
    with pytest.raises(SystemExit) as ei:
        commands.cmd_repo(make_args("repo", action="purge", repo_id="rp_a", yes=False))
    assert ei.value.code == 1
    assert "--yes" in capsys.readouterr().err
    assert mock_client == []  # 连请求都没发


def test_cmd_repo_purge_with_yes(mock_client):
    commands.cmd_repo(make_args("repo", action="purge", repo_id="rp_a", yes=True))
    assert mock_client[0] == ("purge_repo", ("rp_a",), {})


# ── 存储维护（5 个端点）─────────────────────────────────────────────────


def test_cmd_maintenance_backup_with_note_and_repo(mock_client):
    commands.cmd_maintenance(make_args("maintenance", action="backup", note="发版前",
                                       repo="rp_a"))
    assert mock_client[0] == ("maintenance_backup", (), {"note": "发版前", "repo_id": "rp_a"})


def test_cmd_maintenance_backups(mock_client):
    commands.cmd_maintenance(make_args("maintenance", action="backups", repo=""))
    assert mock_client[0] == ("maintenance_backups", (), {"repo_id": ""})


def test_cmd_maintenance_verify(mock_client):
    commands.cmd_maintenance(make_args("maintenance", action="verify", repo="rp_a"))
    assert mock_client[0] == ("maintenance_verify", (), {"repo_id": "rp_a"})


def test_cmd_maintenance_ops_paging(mock_client):
    commands.cmd_maintenance(make_args("maintenance", action="ops", limit=20, offset=40,
                                       repo=""))
    assert mock_client[0][2] == {"limit": 20, "offset": 40, "repo_id": ""}


def test_cmd_maintenance_checkpoint(mock_client):
    commands.cmd_maintenance(make_args("maintenance", action="checkpoint", repo=""))
    assert mock_client[0] == ("maintenance_checkpoint", (), {"repo_id": ""})


# ── 本地日志与回收站 ────────────────────────────────────────────────────


def test_cmd_logs_forwards_filters(mock_client):
    commands.cmd_logs(make_args("logs", kind="frontend", date="2026-10-17",
                                level="error", keyword="超时", tail=50))
    name, args, kwargs = mock_client[0]
    assert name == "logs"
    assert kwargs == {"kind": "frontend", "date": "2026-10-17", "level": "error",
                      "keyword": "超时", "tail": 50}


def test_cmd_trash_list_and_restore(mock_client):
    commands.cmd_trash(make_args("trash", action="list", repo="rp_a"))
    assert mock_client[0] == ("trash_list", (), {"repo_id": "rp_a"})

    mock_client.clear()
    commands.cmd_trash(make_args("trash", action="restore", kind="node",
                                 item_id="n1", repo=""))
    assert mock_client[0] == ("trash_restore", (), {"kind": "node", "item_id": "n1",
                                                    "repo_id": ""})

    # 整图留档（v1.42）：kind=graph 走同一恢复端点（后端为合并式补回）
    mock_client.clear()
    commands.cmd_trash(make_args("trash", action="restore", kind="graph",
                                 item_id="graph-20261017-144222", repo="rp_a"))
    assert mock_client[0] == ("trash_restore", (), {
        "kind": "graph", "item_id": "graph-20261017-144222", "repo_id": "rp_a",
    })


# ── Agent 运维 ──────────────────────────────────────────────────────────


def test_cmd_agent_logs(mock_client):
    commands.cmd_agent(make_args("agent", action="logs", limit=10, full=True, repo=""))
    assert mock_client[0] == ("agent_logs", (), {"limit": 10, "full": True})


def test_cmd_agent_compensate_and_maintain(mock_client):
    commands.cmd_agent(make_args("agent", action="compensate", repo="rp_a"))
    assert mock_client[0] == ("agent_compensate", (), {"repo_id": "rp_a"})

    mock_client.clear()
    commands.cmd_agent(make_args("agent", action="maintain", mode="compress", repo=""))
    assert mock_client[0] == ("agent_maintain", (), {"mode": "compress", "repo_id": ""})


# ── 配置探测（POST /settings/models，v1.34）──────────────────────────────


def test_cmd_config_probe(mock_client):
    commands.cmd_config(make_args("config", action="probe", key="siliconflow",
                                  value="", base_url="", api_key=""))
    assert mock_client[0] == ("probe_models", (), {"provider": "siliconflow",
                                                   "base_url": "", "api_key": ""})


def test_formatter_probe_reports_error_without_4xx(capsys):
    """探测失败不报 4xx：错误摘要必须显示出来（否则像"没模型"）。"""
    from dpim_cli import formatter

    text = formatter.probe_result({"models": [], "error": "AuthenticationError: bad key",
                                   "elapsed_ms": 12})
    assert "探测失败" in text and "AuthenticationError" in text
    text = formatter.probe_result({"models": ["a", "b"], "error": "", "elapsed_ms": 30})
    assert "可用模型 2 个" in text


def test_formatter_trash_list_labels_graph_kind():
    """整图留档（v1.42）必须显示成「整图」——旧实现是 `event ? 事件 : 节点`，
    第三类会**冒充节点**（看起来像误删了一个节点）。"""
    from dpim_cli import formatter

    text = formatter.trash_list({
        "dir": "D:/dpim/trash",
        "items": [
            {"kind": "graph", "id": "graph-20261017-144222", "size": 67967,
             "archived_at": "2026-10-17T06:42:22+00:00",
             "title": "整图留档：51 节点 / 56 边"},
            {"kind": "event", "id": "e1", "size": 12,
             "archived_at": "2026-10-17T06:00:00+00:00", "title": "一段原文"},
        ],
    })
    assert "整图" in text
    assert "整图留档：51 节点 / 56 边" in text
    assert "事件" in text
    assert "共 2 份" in text


# ── status 分层统计取键修复（链 AD）─────────────────────────────────────


def test_status_shows_real_breakdown():
    """`/health` 的分项字段名是 `raw`/`indexed`/`system`…，不是 `status_raw`/`system_nodes`。

    此前取错键 → 每个分项恒显示 0（看起来像"没有数据"）。
    """
    from dpim_cli import formatter

    text = formatter.status({
        "status": "unconfigured", "ai_available": False,
        "ai_unavailable_reason": "未配置任何 AI 提供商（无 AI 模式）",
        "version": "0.4.0", "active_repo_id": "rp_default",
        "queue_depth": 0, "worker_running": True,
        "layers": {
            "event_line": {"total_events": 10, "raw": 0, "indexed": 0, "linked": 10,
                           "failed": 0, "skipped": 0},
            "knowledge_graph": {"total_nodes": 66, "system": 1, "interaction": 1,
                                "data": 49},
        },
    })
    assert "linked=10" in text
    assert "system=1" in text and "data=49" in text
    assert "rp_default" in text
    assert "未配置任何 AI 提供商" in text
