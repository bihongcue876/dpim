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


def _repo(args) -> str:
    """`--repo <id>` 单库作用域（缺省空串 = 活动库）。"""
    return getattr(args, "repo", "") or ""


def _repos(args) -> list[str]:
    """`--repos a,b` 联查作用域（缺省空列表 = 不限定）。"""
    raw = getattr(args, "repos", "") or ""
    return [x.strip() for x in raw.split(",") if x.strip()]


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
    data = _call(client, "ingest", args.content, event_type=args.type, repo_id=_repo(args))
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
                 offset=getattr(args, "offset", 0),
                 repo_id=_repo(args), repo_ids=_repos(args))
    print(formatter.event_list(data, _fmt(args)))


def cmd_event(args):
    """事件相关操作 (view / edit / retry / skip / unskip / delete)。"""
    client = _client(args)
    action = getattr(args, "action", "view")
    eid = args.event_id

    if action == "view":
        data = _call(client, "get_event", eid, repo_id=_repo(args))
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
                 offset=getattr(args, "offset", 0),
                 repo_id=_repo(args), repo_ids=_repos(args))
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
        data = _call(client, "get_node", args.node_id, repo_id=_repo(args))
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


def cmd_edges(args):
    """边列表（GET /edges，v1.37）：图谱页一次取全的读端点。"""
    client = _client(args)
    data = _call(client, "list_edges",
                 node_id=getattr(args, "node", "") or "",
                 source=getattr(args, "source", "") or "",
                 target=getattr(args, "target", "") or "",
                 relation=getattr(args, "relation", "") or "",
                 limit=getattr(args, "limit", 200),
                 offset=getattr(args, "offset", 0),
                 repo_id=_repo(args), repo_ids=_repos(args))
    print(formatter.edge_list(data, _fmt(args)))


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
                 offset=getattr(args, "offset", 0),
                 repo_ids=_repos(args))
    print(formatter.search_results(data, _fmt(args)))


def cmd_feedback(args):
    """检索结果反馈。"""
    client = _client(args)
    accepted = getattr(args, "accept", False) or not getattr(args, "reject", False)
    if getattr(args, "reject", False):
        accepted = False
    data = _call(client, "feedback", args.result_id, accepted, repo_id=_repo(args))
    print(_ok(data, _fmt(args)))


def cmd_config(args):
    """配置管理 (list / set / probe)。"""
    client = _client(args)
    action = getattr(args, "action", "list")

    if action == "list":
        data = _call(client, "get_settings")
        print(formatter.settings(data, _fmt(args)))
    elif action == "set":
        data = _call(client, "update_settings", **{args.key: args.value})
        print(_ok(data, _fmt(args)))
    elif action == "probe":
        # 联网探测某提供商的模型列表：探测失败**不报 4xx**，错误摘要放在 error 里
        data = _call(client, "probe_models",
                     provider=args.key,
                     base_url=getattr(args, "base_url", "") or "",
                     api_key=getattr(args, "api_key", "") or "")
        print(formatter.probe_result(data, _fmt(args)))


# ── 库管理（v1.29+）────────────────────────────────────────────────────────

def cmd_repo(args):
    """库管理：list / show / create / update / delete / activate / refresh /
    generate / adopt / rebuild / purge。"""
    client = _client(args)
    action = getattr(args, "action", "list")
    rid = getattr(args, "repo_id", "") or ""

    if action == "list":
        print(formatter.repo_list(_call(client, "list_repos"), _fmt(args)))
    elif action == "show":
        print(formatter.repo_detail(_call(client, "get_repo", rid), _fmt(args)))
    elif action == "create":
        data = _call(client, "create_repo",
                     name=args.name,
                     group=getattr(args, "group", "") or "",
                     note=getattr(args, "note", "") or "",
                     root=getattr(args, "root", "") or "",
                     root_kind=getattr(args, "kind", "managed"))
        print(_ok(data, _fmt(args)))
    elif action == "update":
        fields: dict = {}
        for cli_key, api_key in (("name", "name"), ("note", "note"), ("group", "group"),
                                 ("root", "root")):
            value = getattr(args, cli_key, None)
            if value:
                fields[api_key] = value
        managed = getattr(args, "managed", None)
        if managed is not None:
            fields["managed"] = str(managed).lower() in ("1", "true", "yes", "on")
        if not fields:
            print("错误: repo update 至少给一项（--name/--note/--group/--root/--managed）",
                  file=sys.stderr)
            sys.exit(1)
        print(_ok(_call(client, "update_repo", rid, **fields), _fmt(args)))
    elif action == "delete":
        print(_ok(_call(client, "delete_repo", rid), _fmt(args)))
    elif action == "activate":
        print(_ok(_call(client, "activate_repo", rid), _fmt(args)))
    elif action == "refresh":
        print(formatter.out(_call(client, "refresh_repo", rid), _fmt(args)))
    elif action == "generate":
        print(_ok(_call(client, "generate_repo", rid), _fmt(args)))
    elif action == "adopt":
        data = _call(client, "adopt_repo",
                     root=args.root,
                     name=getattr(args, "name", "") or "",
                     group=getattr(args, "group", "") or "",
                     adopt_missing=not getattr(args, "no_missing", False))
        print(_ok(data, _fmt(args)))
    elif action == "rebuild":
        print(formatter.out(_call(client, "rebuild_repos"), _fmt(args)))
    elif action == "purge":
        # 危险操作：删 memory.db + graph.json（先自动整库备份）→ 必须显式 --yes
        if not getattr(args, "yes", False):
            print("错误: repo purge 会删除该库的 memory.db 与 graph.json"
                  "（后端会先自动做一次整库备份）。确认请加 --yes", file=sys.stderr)
            sys.exit(1)
        print(formatter.out(_call(client, "purge_repo", rid), _fmt(args)))


# ── 存储维护（v1.30）──────────────────────────────────────────────────────

def cmd_maintenance(args):
    """存储维护：backup / backups / verify / ops / checkpoint。"""
    client = _client(args)
    action = getattr(args, "action", "verify")
    rid = _repo(args)

    if action == "backup":
        data = _call(client, "maintenance_backup",
                     note=getattr(args, "note", "") or "", repo_id=rid)
        print(formatter.out(data, _fmt(args)))
    elif action == "backups":
        print(formatter.backup_list(_call(client, "maintenance_backups", repo_id=rid),
                                    _fmt(args)))
    elif action == "verify":
        print(formatter.verify_result(_call(client, "maintenance_verify", repo_id=rid),
                                      _fmt(args)))
    elif action == "ops":
        print(formatter.op_list(_call(client, "maintenance_ops",
                                      limit=getattr(args, "limit", 100),
                                      offset=getattr(args, "offset", 0),
                                      repo_id=rid), _fmt(args)))
    elif action == "checkpoint":
        print(formatter.out(_call(client, "maintenance_checkpoint", repo_id=rid),
                            _fmt(args)))


# ── 本地日志与回收站（v1.31）──────────────────────────────────────────────

def cmd_logs(args):
    """翻看本地日志尾部（backend-*.log / frontend-*.log）。"""
    client = _client(args)
    data = _call(client, "logs",
                 kind=getattr(args, "kind", "backend"),
                 date=getattr(args, "date", "") or "",
                 level=getattr(args, "level", "") or "",
                 keyword=getattr(args, "keyword", "") or "",
                 tail=getattr(args, "tail", 200))
    print(formatter.logs_result(data, _fmt(args)))


def cmd_trash(args):
    """回收站：list / restore。"""
    client = _client(args)
    action = getattr(args, "action", "list")
    rid = _repo(args)

    if action == "list":
        print(formatter.trash_list(_call(client, "trash_list", repo_id=rid), _fmt(args)))
    elif action == "restore":
        data = _call(client, "trash_restore",
                     kind=getattr(args, "kind", "event"),
                     item_id=args.item_id, repo_id=rid)
        print(_ok(data, _fmt(args)))


# ── Agent 运维 ────────────────────────────────────────────────────────────

def cmd_agent(args):
    """Agent 运维：logs / compensate / maintain。"""
    client = _client(args)
    action = getattr(args, "action", "logs")
    rid = _repo(args)

    if action == "logs":
        print(formatter.agent_logs(_call(client, "agent_logs",
                                         limit=getattr(args, "limit", 50),
                                         full=getattr(args, "full", False)), _fmt(args)))
    elif action == "compensate":
        print(_ok(_call(client, "agent_compensate", repo_id=rid), _fmt(args)))
    elif action == "maintain":
        data = _call(client, "agent_maintain",
                     mode=getattr(args, "mode", "update"), repo_id=rid)
        print(_ok(data, _fmt(args)))


def cmd_graph_clear(args):
    """清空图谱。"""
    client = _client(args)
    data = _call(client, "clear_graph")
    print(_ok(data, _fmt(args)))
