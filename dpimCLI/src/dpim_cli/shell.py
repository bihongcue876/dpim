"""交互式 Shell 模式 — prompt_toolkit 驱动。"""

import os
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from . import commands as cmd_mod
from . import config as cli_config
from . import formatter
from .api_client import DPIMClient
from .parser import parse
from .completions import DPIMCompleter


SHELL_STYLE = Style.from_dict({
    "prompt": "ansicyan bold",
})

# Shell 控制命令（不由 commands 处理）
SHELL_COMMANDS = {"quit", "exit", "\\q", "clear", "history", "help", "format", "timing", "-h"}


def run_shell(api_url: str = "", output_format: str = ""):
    """启动交互式 Shell。"""
    url = api_url or cli_config.get("api_url")
    fmt = output_format or cli_config.get("format")

    # 验证连接
    _print_banner(url)

    session = PromptSession(
        history=InMemoryHistory(),
        completer=DPIMCompleter(),
        style=SHELL_STYLE,
        complete_while_typing=True,
    )

    timing = False
    cur_fmt = fmt

    while True:
        try:
            text = session.prompt("dpim> ", style="class:prompt")
        except (KeyboardInterrupt, EOFError):
            print()
            break

        text = text.strip()
        if not text:
            continue

        # ── Shell 控制命令 ──
        handled = _handle_shell_commands(text, session, timing)
        if handled is True:
            break
        if handled is not None:
            # Shell 状态变更
            if isinstance(handled, dict):
                if "timing" in handled:
                    timing = handled["timing"]
                if "format" in handled:
                    cur_fmt = handled["format"]
            continue

        # ── 解析 + 执行 ──
        start = time.time()
        _execute(text, cur_fmt, url)
        if timing:
            elapsed = time.time() - start
            print(f"\033[90m({elapsed * 1000:.0f}ms)\033[0m")


def _print_banner(url: str):
    """打印 Shell 启动信息。"""
    try:
        client = DPIMClient(base_url=url)
        health = client.health()
        ai = "是" if health.get("ai_available") else "否"
        print(f"已连接到 DPIM 服务: {url}")
        print(f"  状态: {health.get('status', '?')} | AI: {ai}"
              f"  事件: {health.get('layers', {}).get('event_line', {}).get('total_events', 0)}"
              f"  节点: {health.get('layers', {}).get('knowledge_graph', {}).get('total_nodes', 0)}")
    except Exception as e:
        print(f"⚠ 无法连接到 DPIM 服务 ({url}): {e}")

    print("输入 help 查看命令列表，quit 退出。")


def _handle_shell_commands(text: str, session, timing: bool):
    """处理 Shell 内部命令。返回 True 退出，False/None 继续。"""
    if text in ("quit", "exit", "\\q"):
        return True

    if text == "clear":
        os.system("cls" if os.name == "nt" else "clear")
        return {}

    if text == "history":
        for i, h in enumerate(session.history.get_strings(), 1):
            print(f"  {i:4d}  {h}")
        return {}

    if text == "help":
        _show_help()
        return {}

    if text.startswith("help "):
        _show_help()
        return {}

    if text == "-h":
        _show_help()
        return {}

    if text.startswith("format "):
        new_fmt = text.split(None, 1)[1].strip()
        if new_fmt in ("table", "json", "yaml"):
            print(f"输出格式已切换为: {new_fmt}")
            return {"format": new_fmt}
        print("支持的格式: table, json, yaml")
        return {}

    if text == "timing on":
        print("命令耗时已启用")
        return {"timing": True}

    if text == "timing off":
        print("命令耗时已关闭")
        return {"timing": False}

    return None


def _execute(text: str, fmt: str, api_url: str):
    """解析并执行一条命令。"""
    cmd_name, kwargs = parse(text)
    if not cmd_name:
        return

    # Shell 控制命令已提前处理，此处只处理业务命令
    if cmd_name in SHELL_COMMANDS:
        return

    # 处理子命令: "event view <id>" → action=view
    pos = kwargs.get("positional", [])
    if cmd_name in ("event", "node", "edge", "config", "graph"):
        action = kwargs.get("action", "")
        if not action and pos and pos[0] in (
            "view", "edit", "retry", "skip", "unskip",
            "delete", "create", "set", "list", "clear"
        ):
            kwargs["action"] = pos[0]
            kwargs["positional"] = pos[1:]
        elif not action:
            kwargs["action"] = "view" if cmd_name in ("event", "node") else (
                "create" if cmd_name == "edge" else "list" if cmd_name == "config" else "clear"
            )

    # 补全反馈的位置参数
    if cmd_name == "feedback" and not kwargs.get("result_id") and pos:
        kwargs["result_id"] = pos[0]
        kwargs["positional"] = pos[1:]

    # 查找命令处理函数
    cmd_fn_name = _resolve_handler(cmd_name)
    if not cmd_fn_name:
        print(f"未知命令: {cmd_name}  (输入 help 查看命令列表)")
        return

    handler = getattr(cmd_mod, cmd_fn_name, None)
    if not handler:
        print(f"未实现的命令: {cmd_name}")
        return

    # 构建 args 对象
    args = _build_args(cmd_name, kwargs, fmt, api_url)
    handler(args)


def _resolve_handler(cmd_name: str) -> str:
    """命令名 → commands 模块中的函数名。"""
    mapping = {
        "status": "cmd_status",
        "state-key": "cmd_state_key",
        "ingest": "cmd_ingest",
        "events": "cmd_events",
        "event": "cmd_event",
        "nodes": "cmd_nodes",
        "node": "cmd_node",
        "edge": "cmd_edge",
        "search": "cmd_search",
        "feedback": "cmd_feedback",
        "config": "cmd_config",
        "graph": "cmd_graph_clear",
    }
    return mapping.get(cmd_name, "")


def _build_args(cmd_name: str, kwargs: dict, fmt: str, api_url: str):
    """将 Shell 解析结果转为类似 argparse.Namespace 的对象。"""

    class Args:
        pass

    args = Args()
    args.format = fmt
    args.api = api_url
    args.command = cmd_name

    pos = kwargs.get("positional", [])

    # 业务字段填充
    if cmd_name == "ingest":
        args.content = pos[0] if pos else kwargs.get("content", "")
        args.type = kwargs.get("type", "interaction")
    elif cmd_name == "search":
        args.query = pos[0] if pos else kwargs.get("query", "")
        args.type = kwargs.get("type", "all")
        args.hops = int(kwargs.get("hops", 2))
        args.limit = int(kwargs.get("limit", 20))
        args.offset = int(kwargs.get("offset", 0))
    elif cmd_name == "status":
        pass
    elif cmd_name == "state-key":
        pass
    elif cmd_name == "events":
        args.type = kwargs.get("type", "")
        args.status = kwargs.get("status", "")
        args.limit = int(kwargs.get("limit", 20))
        args.offset = int(kwargs.get("offset", 0))
    elif cmd_name == "event":
        args.event_id = pos[0] if pos else kwargs.get("event_id", "")
        args.action = kwargs.get("action", "view")
        args.content = kwargs.get("content", pos[1] if len(pos) > 1 else "")
    elif cmd_name == "nodes":
        args.type = kwargs.get("type", "")
        args.limit = int(kwargs.get("limit", 20))
        args.offset = int(kwargs.get("offset", 0))
    elif cmd_name == "node":
        args.node_id = pos[0] if pos else kwargs.get("node_id", "")
        args.action = kwargs.get("action", "")  # 空值时自动推断
        args.content = pos[1] if len(pos) > 1 else kwargs.get("content", "")
        args.title = kwargs.get("title", "")
        args.event = kwargs.get("event", "")
        args.force = str(kwargs.get("force", "false")).lower() in ("true", "1")
        args.type = kwargs.get("type", "data")
    elif cmd_name == "edge":
        args.action = kwargs.get("action", "create")
        args.source = kwargs.get("source", "")
        args.target = kwargs.get("target", "")
        args.relation = kwargs.get("relation", "")
        args.event = kwargs.get("event", "")
    elif cmd_name == "feedback":
        args.result_id = pos[0] if pos else kwargs.get("result_id", "")
        args.accept = str(kwargs.get("accept", "false")).lower() in ("true", "1")
        args.reject = str(kwargs.get("reject", "false")).lower() in ("true", "1")
    elif cmd_name == "config":
        args.action = kwargs.get("action", "list")
        args.key = pos[0] if pos else kwargs.get("key", "")
        args.value = pos[1] if len(pos) > 1 else kwargs.get("value", "")
    elif cmd_name == "graph":
        args.action = kwargs.get("action", "clear")

    return args


def _show_help():
    """显示帮助信息。"""
    print("""
\033[36mDPIM CLI 命令列表\033[0m

\033[33m系统状态\033[0m
  status              查看系统健康状态
  state-key           显示状态校验密钥

\033[33m事件管理\033[0m
  ingest <内容>       写入事件 [--type interaction|data|source]
  events              分页事件列表 [--type] [--status] [--limit N]
  event <id>          查看事件详情
  event edit <id>     修订事件内容
  event retry <id>    重试 failed 事件
  event skip <id>     跳过事件
  event unskip <id>   取消跳过
  event delete <id>   删除事件

\033[33m节点管理\033[0m
  nodes               分页节点列表 [--type] [--limit N]
  node <id>           查看节点详情
  node create         创建节点 --title <标题> [--content] [--event]
  node edit <id>      修改节点内容
  node delete <id>    删除节点 [--force]

\033[33m边管理\033[0m
  edge create         创建边 --source <id> --target <id> --relation <关系>
  edge delete         删除边 --source <id> --target <id>

\033[33m检索与反馈\033[0m
  search <关键词>     混合检索 [--type] [--hops N] [--limit N]
  feedback <id>       反馈 --accept | --reject

\033[33m其他\033[0m
  config              列出配置项
  config set <k> <v>  修改配置项
  graph clear         清空图谱

\033[33mShell 控制\033[0m
  help / -h           显示帮助
  quit / exit         退出
  format <table|json|yaml>  切换输出格式
  timing on|off       命令计时
  clear               清屏
  history             查看历史
""")
