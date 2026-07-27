"""命令处理函数 — 为每个命令封装 API 调用 + 格式化输出。"""

import sys

from .api_client import DPIMClient, DPIMError, ConnectionError
from . import formatter


def _fmt(args) -> str:
    """获取输出格式（命令行参数优先，否则默认 table）。"""
    return getattr(args, "format", "table") if hasattr(args, "format") else "table"


def _client(args) -> DPIMClient:
    """从命令行参数创建客户端。"""
    url = getattr(args, "api", "") or getattr(args, "api_url", "") or "http://localhost:8000"
    return DPIMClient(base_url=url)


def _ok(data: dict, fmt: str = "table") -> str:
    """通用成功消息。"""
    return formatter.ok_message(data, fmt)


def _call(client, method: str, *args_method, fmt: str = "table", **kwargs):
    """调用 API 方法并处理错误。"""
    try:
        fn = getattr(client, method)
        data = fn(*args_method, **kwargs)
        return data
    except ConnectionError as e:
        print(f"错误: 无法连接到 DPIM 服务 - {e}", file=sys.stderr)
        sys.exit(1)
    except DPIMError as e:
        print(f"错误 [{e.code}]: {e.message}", file=sys.stderr)
        sys.exit(1)


# ── 命令处理函数 ──

def cmd_status(args):
    """展示系统健康状态。"""
    client = _client(args)
    data = _call(client, "health")
    print(formatter.status(data, _fmt(args)))


def cmd_state_key(args):
    """显示状态校验密钥。"""
    client = _client(args)
    data = _call(client, "state_key")
    print(formatter.state_key(data, _fmt(args)))


def cmd_ingest(args):
    """写入事件。"""
    client = _client(args)
    data = _call(client, "ingest", args.content, event_type=args.type)
    if _fmt(args) == "table":
        print(formatter.ingest_result(data, _fmt(args)))
    else:
        print(formatter.out(data, _fmt(args)))


def cmd_events(args):
    """分页事件列表。"""
    client = _client(args)
    data = _call(client, "list_events",
                 type=getattr(args, "type", "") or "",
                 status=getattr(args, "status", "") or "",
                 limit=getattr(args, "limit", 20),
                 offset=getattr(args, "offset", 0))
    print(formatter.event_list(data, _fmt(args)))


def cmd_event(args):
    """事件相关操作 (view / edit / retry / skip / unskip / delete)。"""
    client = _client(args)
    action = getattr(args, "action", "view")
    eid = args.event_id

    if action == "view":
        data = _call(client, "get_event", eid)
        print(formatter.event_detail(data, _fmt(args)))
    elif action == "edit":
        data = _call(client, "edit_event", eid, args.content)
        print(_ok(data, _fmt(args)))
    elif action == "retry":
        data = _call(client, "update_event_status", eid, "indexed")
        print(_ok(data, _fmt(args)))
    elif action == "skip":
        data = _call(client, "update_event_status", eid, "skipped")
        print(_ok(data, _fmt(args)))
    elif action == "unskip":
        data = _call(client, "update_event_status", eid, "indexed")
        print(_ok(data, _fmt(args)))
    elif action == "delete":
        data = _call(client, "delete_event", eid)
        print(_ok(data, _fmt(args)))


def cmd_nodes(args):
    """分页节点列表。"""
    client = _client(args)
    data = _call(client, "list_nodes",
                 type=getattr(args, "type", "") or "",
                 limit=getattr(args, "limit", 20),
                 offset=getattr(args, "offset", 0))
    print(formatter.node_list(data, _fmt(args)))


def cmd_node(args):
    """节点相关操作 (view / create / edit / delete)。"""
    client = _client(args)

    # 自动推断 action
    action = getattr(args, "action", "")
    if not action:
        title = getattr(args, "title", "")
        if title:
            action = "create"
        elif getattr(args, "force", False):
            action = "delete"
        elif args.node_id and args.content:
            action = "edit"
        else:
            action = "view"

    if action == "view":
        data = _call(client, "get_node", args.node_id)
        print(formatter.node_detail(data, _fmt(args)))
    elif action == "create":
        data = _call(client, "create_node",
                     title=args.title,
                     content=getattr(args, "content", ""),
                     source_event_id=getattr(args, "event", ""))
        if _fmt(args) == "table":
            print(f"[OK] 节点已创建: {data.get('node_id', '')}")
        else:
            print(formatter.out(data, _fmt(args)))
    elif action == "edit":
        data = _call(client, "edit_node", args.node_id, args.content)
        print(_ok(data, _fmt(args)))
    elif action == "delete":
        data = _call(client, "delete_node", args.node_id,
                     force=getattr(args, "force", False))
        print(_ok(data, _fmt(args)))


def cmd_edge(args):
    """边相关操作 (create / delete)。"""
    client = _client(args)
    action = getattr(args, "action", "create")

    if action == "create":
        data = _call(client, "create_edge",
                     source=args.source,
                     target=args.target,
                     relation=args.relation,
                     evidence_event_id=getattr(args, "event", ""))
        print(_ok(data, _fmt(args)))
    elif action == "delete":
        data = _call(client, "delete_edge",
                     source=args.source,
                     target=args.target)
        print(_ok(data, _fmt(args)))


def cmd_search(args):
    """混合检索。"""
    client = _client(args)
    # CLI 参数名 → API 参数名映射
    sf = getattr(args, "type", "all")
    if sf == "all":
        sf = "all"
    data = _call(client, "search",
                 query=args.query,
                 source_filter=sf,
                 max_hops=getattr(args, "hops", 2),
                 limit=getattr(args, "limit", 20),
                 offset=getattr(args, "offset", 0))
    print(formatter.search_results(data, _fmt(args)))


def cmd_feedback(args):
    """检索结果反馈。"""
    client = _client(args)
    accepted = getattr(args, "accept", False) or not getattr(args, "reject", False)
    if getattr(args, "reject", False):
        accepted = False
    data = _call(client, "feedback", args.result_id, accepted)
    print(_ok(data, _fmt(args)))


def cmd_config(args):
    """配置管理 (list / set)。"""
    client = _client(args)
    action = getattr(args, "action", "list")

    if action == "list":
        data = _call(client, "get_settings")
        print(formatter.settings(data, _fmt(args)))
    elif action == "set":
        data = _call(client, "update_settings", **{args.key: args.value})
        print(_ok(data, _fmt(args)))


def cmd_graph_clear(args):
    """清空图谱。"""
    client = _client(args)
    data = _call(client, "clear_graph")
    print(_ok(data, _fmt(args)))
