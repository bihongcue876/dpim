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
        f"最后事件:  {_time_str(data.get('last_event_at', ''))}",
        "",
        f"事件:      {el.get('total_events', 0)} 条 "
        f"(raw={el.get('status_raw',0)} indexed={el.get('status_indexed',0)} "
        f"linked={el.get('status_linked',0)} failed={el.get('status_failed',0)} "
        f"skipped={el.get('status_skipped',0)})",
        f"节点:      {kg.get('total_nodes', 0)} 个 "
        f"(system={kg.get('system_nodes',0)} interaction={kg.get('interaction_nodes',0)} "
        f"data={kg.get('data_nodes',0)})",
    ]
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
    """格式化写入结果。"""
    if fmt != "table":
        return out(data, fmt)
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
