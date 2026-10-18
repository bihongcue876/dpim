"""结果格式化输出 — table / json / yaml。"""

import json
from datetime import datetime

import tabulate
import yaml


def _short_id(eid: str, length: int = 16) -> str:
    """截断 ID 用于表格显示。"""
    return eid[:length] + "…" if len(eid) > length else eid


def _time_str(iso: str) -> str:
    """ISO 时间 → 本地可读格式。"""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return iso[:16] if iso else "-"


# 回收站留档类型标签（v1.42 增整图）：kind → (中文, 终端颜色)
_TRASH_KIND = {
    "event": ("事件", "cyan"),
    "node": ("节点", "blue"),
    "graph": ("整图", "yellow"),
}


def _tag(text: str, color: str = "") -> str:
    """终端彩色标签（dark 主题常用 ANSI）。"""
    colors = {
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "cyan": "\033[36m",
        "red": "\033[31m",
        "gray": "\033[90m",
        "reset": "\033[0m",
    }
    if color and color in colors:
        return f"{colors[color]}{text}{colors['reset']}"
    return text


def _confidence_bar(conf: float, width: int = 8) -> str:
    """置信度条。"#"" 填充。"""
    filled = round(conf * width)
    bar = "#" * filled + "-" * (width - filled)
    return bar


def _health_color(status: str) -> str:
    if status == "ok":
        return "green"
    if status == "degraded":
        return "yellow"
    return "red"


# ── 核心格式化 ──

def out(data, fmt: str = "table"):
    """
    根据 fmt 输出数据。
    如果是字符串直接返回，如果是 dict/list 按格式序列化。
    """
    if isinstance(data, str):
        return data
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)
    if fmt == "yaml":
        return yaml.dump(data, allow_unicode=True, default_flow_style=False,
                         sort_keys=False)
    # table 模式下返回原始数据供具体格式化函数处理
    return data


def status(data: dict, fmt: str = "table") -> str:
    """格式化系统状态。"""
    if fmt != "table":
        return out(data, fmt)

    layers = data.get("layers", {})
    el = layers.get("event_line", {})
    kg = layers.get("knowledge_graph", {})
    status_text = data.get("status", "unknown")
    lines = [
        f"状态:      {_tag(status_text.upper(), _health_color(status_text))}",
        f"AI 可用:   {_tag('是' if data.get('ai_available') else '否', 'green' if data.get('ai_available') else 'red')}",
        f"版本:      {data.get('version', '-')}",
        f"活动库:    {data.get('active_repo_id') or '-'}",
        f"队列:      {data.get('queue_depth', 0)} 条 / worker "
        f"{_tag('运行中', 'green') if data.get('worker_running') else _tag('停止', 'red')}",
        f"最后事件:  {_time_str(data.get('last_event_at', ''))}",
        "",
        # 分层统计的字段名以 `/health` 实际下发为准（`raw`/`indexed`/… 与
        # `system`/`interaction`/`data`）——此前写成 `status_raw`/`system_nodes`，
        # 于是每个分项都恒显示 0（看起来像"没有数据"，其实是取错了键）。
        f"事件:      {el.get('total_events', 0)} 条 "
        f"(raw={el.get('raw',0)} indexed={el.get('indexed',0)} "
        f"linked={el.get('linked',0)} failed={el.get('failed',0)} "
        f"skipped={el.get('skipped',0)})",
        f"节点:      {kg.get('total_nodes', 0)} 个 "
        f"(system={kg.get('system',0)} interaction={kg.get('interaction',0)} "
        f"data={kg.get('data',0)})",
    ]
    # 未配置 AI 与「配了但连不上」严格区分（v1.34 三态）：原因必须看得见
    if data.get("ai_unavailable_reason"):
        lines.append(f"AI 原因:   {data['ai_unavailable_reason']}")
    return "\n".join(lines)


def state_key(data: dict, fmt: str = "table") -> str:
    """格式化状态校验密钥。"""
    if fmt != "table":
        return out(data, fmt)
    return (
        f"状态密钥:  {data.get('hash', '-')}\n"
        f"最近变更:  {_time_str(data.get('changed_at', ''))}"
    )


def ingest_result(data: dict, fmt: str = "table") -> str:
    """格式化写入结果（含对话指令：/压缩、/merge、/data: 等的执行结果）。"""
    if fmt != "table":
        return out(data, fmt)
    if data.get("command_triggered"):
        return f"指令结果\n  {data.get('message', '(无消息)')}"
    return (
        f"事件已写入\n"
        f"  event_id: {data.get('event_id', '-')}\n"
        f"  status:   {data.get('status', '-')}"
    )


def event_list(data: dict, fmt: str = "table") -> str:
    """格式化事件列表。"""
    items = data.get("items", [])
    total = data.get("total", 0)

    if fmt != "table":
        return out(data, fmt)

    if not items:
        return "(无事件)"

    rows = []
    for ev in items:
        rows.append([
            _short_id(ev.get("event_id", ""), 16),
            _tag(ev.get("event_type", ""), "cyan"),
            _tag(ev.get("status", ""), "green" if ev.get("status") == "linked" else "yellow"),
            _time_str(ev.get("created_at", "")),
        ])
    table = tabulate.tabulate(
        rows,
        headers=["event_id", "类型", "状态", "时间"],
        tablefmt="simple",
        stralign="left",
    )
    return f"{table}\n共 {total} 条"


def event_detail(data: dict, fmt: str = "table") -> str:
    """格式化事件详情。"""
    if fmt != "table":
        return out(data, fmt)
    if isinstance(data, dict) and "error" in data:
        return str(data)
    return (
        f"event_id:    {data.get('event_id', '-')}\n"
        f"类型:        {data.get('event_type', '-')}\n"
        f"状态:        {data.get('status', '-')}\n"
        f"时间:        {_time_str(data.get('created_at', ''))}\n"
        f"content_hash: {data.get('content_hash', '-')}\n"
        f"graph_refs:  {data.get('graph_refs', '[]')}\n"
        f"\n--- raw_content ---\n{data.get('raw_content', '')}"
    )


def ok_message(data: dict, fmt: str = "table") -> str:
    """格式化成功消息（通用）。"""
    if fmt != "table":
        return out(data, fmt)
    msg = data.get("message", "操作成功")
    return f"✅ {msg}"


def node_list(data: dict, fmt: str = "table") -> str:
    """格式化节点列表。"""
    items = data.get("items", [])
    total = data.get("total", 0)

    if fmt != "table":
        return out(data, fmt)

    if not items:
        return "(无节点)"

    rows = []
    for n in items:
        rows.append([
            _short_id(n.get("node_id", ""), 12),
            n.get("title", "")[:30],
            _tag(n.get("node_type", ""), "blue"),
            f"{n.get('confidence', 0):.2f}",
        ])
    table = tabulate.tabulate(
        rows,
        headers=["node_id", "title", "类型", "置信度"],
        tablefmt="simple",
        stralign="left",
    )
    return f"{table}\n共 {total} 条"


def node_detail(data: dict, fmt: str = "table") -> str:
    """格式化节点详情。"""
    if fmt != "table":
        return out(data, fmt)

    edges = data.get("edges", [])
    source_refs = data.get("source_refs", [])

    lines = [
        f"node_id:    {data.get('node_id', '-')}",
        f"title:      {data.get('title', '')}",
        f"类型:       {_tag(data.get('node_type', ''), 'blue')}",
        f"置信度:     {data.get('confidence', 0):.2f}  {_confidence_bar(data.get('confidence', 0))}",
        f"metadata:   {json.dumps(data.get('metadata', {}), ensure_ascii=False)}",
        "",
        f"--- content ---\n{data.get('content', '')}",
    ]

    if source_refs:
        lines.append("")
        lines.append("--- 源事件 ---")
        for sr in source_refs:
            valid = _tag("V", "green") if sr.get("valid") else _tag("X", "red")
            lines.append(f"  {valid} {_short_id(sr.get('event_id',''), 16)}  hash={sr.get('hash','')[:8]}")

    if edges:
        lines.append("")
        lines.append(f"--- 关联边 ({len(edges)}) ---")
        for e in edges:
            lines.append(f"  {_short_id(e.get('source',''), 12)} -> {_short_id(e.get('target',''), 12)}  :  {e.get('relation','')}")

    return "\n".join(lines)


def search_results(data: dict, fmt: str = "table") -> str:
    """格式化检索结果。"""
    results = data.get("results", [])
    total = data.get("total", 0)
    degraded = data.get("degraded", False)

    if fmt != "table":
        return out(data, fmt)

    if not results:
        return "(无匹配结果)"

    rows = []
    for r in results:
        st = r.get("source_type", "")
        st_color = "green" if st == "interaction" else ("yellow" if st == "data" else "blue")
        rows.append([
            r.get("title", "")[:24],
            _tag(st, st_color),
            f"{r.get('score', 0):.3f}",
            f"{r.get('confidence', 0):.2f}",
            r.get("snippet", "")[:40],
        ])
    table = tabulate.tabulate(
        rows,
        headers=["title", "类型", "得分", "置信", "snippet"],
        tablefmt="simple",
        stralign="left",
    )
    mode = "降级" if degraded else "正常"
    return f"{table}\n共 {total} 条 ({mode}模式)"


def settings(data: dict, fmt: str = "table") -> str:
    """格式化配置项。"""
    if fmt != "table":
        return out(data, fmt)

    if not data:
        return "(无配置项)"

    rows = []
    for k, v in data.items():
        # 隐藏 API Key
        if "api_key" in k.lower() and v:
            v = v[:4] + "****" if len(v) > 4 else "****"
        rows.append([k, str(v)])
    return tabulate.tabulate(rows, headers=["配置项", "值"], tablefmt="simple", stralign="left")


# ── v1.39（链 AD）：补齐维护/运维类端点的输出 ───────────────────────────────


def edge_list(data: dict, fmt: str = "table") -> str:
    """格式化边列表（GET /edges，v1.37）。"""
    if fmt != "table":
        return out(data, fmt)
    items = data.get("items", [])
    total = data.get("total", 0)
    if not items:
        return "(无边)"
    rows = [
        [
            _short_id(e.get("source", ""), 12),
            "->",
            _short_id(e.get("target", ""), 12),
            e.get("relation", "")[:30],
            _short_id(e.get("evidence_event_id", ""), 12) or "-",
            e.get("repo_id", "") or "-",
        ]
        for e in items
    ]
    table = tabulate.tabulate(
        rows,
        headers=["source", "", "target", "relation", "evidence", "库"],
        tablefmt="simple",
        stralign="left",
    )
    return (
        f"{table}\n共 {total} 条（本页 {len(items)}；"
        f"limit={data.get('limit')} offset={data.get('offset')}）"
    )


def repo_list(data: dict, fmt: str = "table") -> str:
    """格式化库登记列表（GET /repos：字段名是 `repos`，不是 `items`）。"""
    if fmt != "table":
        return out(data, fmt)
    repos = data.get("repos", [])
    active = data.get("active_repo_id", "")
    if not repos:
        return "(无书目)"
    rows = []
    for r in repos:
        flags = []
        if r.get("active"):
            flags.append(_tag("活动", "green"))
        if not r.get("managed"):
            flags.append(_tag("休眠", "gray"))
        elif not r.get("loaded"):
            flags.append(_tag("未加载", "yellow"))
        if r.get("load_error"):
            flags.append(_tag(str(r["load_error"])[:24], "red"))
        rows.append([
            r.get("repo_id", ""),
            r.get("name", "")[:20],
            (r.get("group") or "-"),
            r.get("root_kind", ""),
            r.get("total_events") if r.get("total_events") is not None else "-",
            r.get("total_nodes") if r.get("total_nodes") is not None else "-",
            " ".join(flags) or "-",
        ])
    table = tabulate.tabulate(
        rows,
        headers=["repo_id", "名称", "分组", "类型", "事件", "节点", "状态"],
        tablefmt="simple",
        stralign="left",
    )
    return f"{table}\n活动库: {active or '-'}"


def repo_detail(data: dict, fmt: str = "table") -> str:
    """格式化库详情（GET /repos/{id}，含可选 status_counts）。"""
    if fmt != "table":
        return out(data, fmt)
    lines = [
        f"repo_id:   {data.get('repo_id', '-')}",
        f"名称:      {data.get('name', '')}",
        f"分组:      {data.get('group') or '-'}",
        f"类型:      {data.get('root_kind', '')}（受管={data.get('managed')} 已加载={data.get('loaded')}）",
        f"活动:      {'是' if data.get('active') else '否'}",
        f"备注:      {data.get('note', '') or '-'}",
        f"事件/节点: {data.get('total_events')} / {data.get('total_nodes')}",
        f"db:        {data.get('db_path', '-')}",
        f"json:      {data.get('json_path', '-')}",
    ]
    if data.get("load_error"):
        lines.append(f"未加载原因: {_tag(data['load_error'], 'red')}")
    counts = data.get("status_counts")
    if counts:
        lines.append(f"事件状态:  {json.dumps(counts, ensure_ascii=False)}")
    return "\n".join(lines)


def backup_list(data: dict, fmt: str = "table") -> str:
    """格式化整库备份列表（GET /maintenance/backups：字段名是 `backups`）。"""
    if fmt != "table":
        return out(data, fmt)
    backups = data.get("backups", [])
    if not backups:
        return "(无备份)"
    rows = []
    for b in backups:
        manifest = b.get("manifest") or {}
        rows.append([
            b.get("stamp", ""),
            _tag(f"{b.get('bytes', 0) / 1024:.0f} KiB", "cyan"),
            str(manifest.get("total_events", "-")),
            str(manifest.get("total_nodes", "-")),
            (manifest.get("note", "") or "")[:24],
        ])
    table = tabulate.tabulate(
        rows,
        headers=["时间戳", "体积", "事件", "节点", "备注"],
        tablefmt="simple",
        stralign="left",
    )
    return f"{table}\n共 {len(backups)} 份"


def verify_result(data: dict, fmt: str = "table") -> str:
    """格式化一致性校验（POST /maintenance/verify）。"""
    if fmt != "table":
        return out(data, fmt)
    ok = data.get("ok")
    lines = [f"结论: {_tag('一致', 'green') if ok else _tag('有不一致项', 'red')}", ""]
    for check in data.get("checks", []):
        mark = _tag("✓", "green") if check.get("ok") else _tag("✗", "red")
        detail = check.get("detail", "")
        lines.append(f"  {mark} {check.get('name', '')}" + (f"  {detail}" if detail else ""))
    sizes = data.get("sizes") or {}
    counts = data.get("counts") or {}
    if sizes:
        lines.append("")
        lines.append(f"体积: {json.dumps(sizes, ensure_ascii=False)}")
    if counts:
        lines.append(f"计数: {json.dumps(counts, ensure_ascii=False)}")
    return "\n".join(lines)


def op_list(data: dict, fmt: str = "table") -> str:
    """格式化图层操作日志（GET /maintenance/ops：字段名是 `ops`）。"""
    if fmt != "table":
        return out(data, fmt)
    ops = data.get("ops", [])
    total = data.get("total", 0)
    if not ops:
        return "(无操作日志：该库图层还没有落盘过差分)"
    rows = [
        [
            op.get("op_id", ""),
            _time_str(op.get("created_at", "")),
            _tag(op.get("op_kind", ""), "blue"),
            op.get("actor", "") or "system",
            (op.get("reason", "") or "")[:28],
        ]
        for op in ops
    ]
    table = tabulate.tabulate(
        rows,
        headers=["op_id", "时间", "类型", "actor", "原因"],
        tablefmt="simple",
        stralign="left",
    )
    return f"{table}\n本页 {len(ops)} 条 / 共 {total} 条"


def logs_result(data: dict, fmt: str = "table") -> str:
    """格式化本地日志尾部（GET /logs）。"""
    if fmt != "table":
        return out(data, fmt)
    lines = data.get("lines", [])
    header = (
        f"通道: {data.get('kind')}  日期: {data.get('date') or '-'}  "
        f"目录: {data.get('dir', '-')}\n"
        f"可用文件 {len(data.get('files', []))} 份；本页 {len(lines)} 行"
        + ("（过滤后匹配行数超过 tail，仅显示最新部分）" if data.get("truncated") else "")
    )
    if not lines:
        return header + "\n(该日期没有日志行)"
    return header + "\n" + "\n".join(lines)


def trash_list(data: dict, fmt: str = "table") -> str:
    """格式化回收站留档清单（GET /trash；v1.42 增整图留档 kind=graph）。"""
    if fmt != "table":
        return out(data, fmt)
    items = data.get("items", [])
    if not items:
        return f"(回收站为空)  目录: {data.get('dir', '-')}"
    rows = [
        [
            _tag(*_TRASH_KIND.get(it.get("kind"), ("留档", ""))),
            _short_id(it.get("id", ""), 16),
            (it.get("title", "") or "")[:28],
            _time_str(it.get("archived_at", "")),
            f"{it.get('size', 0)} B",
        ]
        for it in items
    ]
    table = tabulate.tabulate(
        rows,
        headers=["类型", "id", "摘要", "留档时间", "大小"],
        tablefmt="simple",
        stralign="left",
    )
    return f"{table}\n共 {len(items)} 份  目录: {data.get('dir', '-')}"


def agent_logs(data: dict, fmt: str = "table") -> str:
    """格式化 AI 调用日志（GET /agent/logs，新→旧）。"""
    if fmt != "table":
        return out(data, fmt)
    logs = data.get("logs", [])
    if not logs:
        return "(无 AI 调用记录)"
    rows = [
        [
            _time_str(item.get("timestamp", "")),
            _tag(item.get("role", ""), "cyan"),
            (item.get("model", "") or "")[:24],
            _tag("失败", "red") if item.get("error") else _tag("成功", "green"),
            (item.get("error", "") or "")[:36],
        ]
        for item in logs
    ]
    table = tabulate.tabulate(
        rows,
        headers=["时间", "角色", "模型", "结果", "错误"],
        tablefmt="simple",
        stralign="left",
    )
    return f"{table}\n共 {len(logs)} 条（新→旧）"


def probe_result(data: dict, fmt: str = "table") -> str:
    """格式化模型探测结果（POST /settings/models：失败不报 4xx，错误在 `error`）。"""
    if fmt != "table":
        return out(data, fmt)
    models = data.get("models", [])
    error = data.get("error", "")
    elapsed = data.get("elapsed_ms", 0)
    if error:
        return f"探测失败（{elapsed} ms）\n  {_tag(error, 'red')}"
    if not models:
        return f"探测完成（{elapsed} ms）但没有返回任何模型"
    return (
        f"可用模型 {len(models)} 个（{elapsed} ms）:\n  "
        + "\n  ".join(models)
    )
