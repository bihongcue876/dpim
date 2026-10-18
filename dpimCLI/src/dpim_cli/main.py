"""dpim CLI 入口 — 单次命令模式 (argparse) / 交互式 Shell 模式。"""

import sys
import argparse

from . import config as cli_config
from . import commands
from .shell import run_shell


def _parser() -> argparse.ArgumentParser:
    """构建全局参数解析器。"""
    p = argparse.ArgumentParser(
        prog="dpim",
        description="DPIM 命令行交互工具 — 管理双区智能内存",
        add_help=False,
    )
    # 全局选项
    p.add_argument("--api", metavar="URL", help=f"后端 API 地址 (默认: {cli_config.get('api_url')})")
    p.add_argument("--format", choices=["table", "json", "yaml"], help="输出格式")
    p.add_argument("-h", "--help", action="store_true", dest="show_help")
    return p


def _build_subparsers(parent: argparse.ArgumentParser):
    """为所有命令构建子解析器。"""
    sub = parent.add_subparsers(dest="command", metavar="")

    def _sp(name: str, help_: str, global_opts: bool = True):
        """新建子解析器；global_opts 时挂全局选项（允许 --api/--format 放命令后）。

        default=argparse.SUPPRESS：用户未提供时不写 namespace，
        避免子 parser 的默认值覆盖命令前置的全局参数（argparse 陷阱）。
        """
        sp = sub.add_parser(name, help=help_)
        if global_opts:
            sp.add_argument("--api", metavar="URL",
                            default=argparse.SUPPRESS, help=argparse.SUPPRESS)
            sp.add_argument("--format", choices=["table", "json", "yaml"],
                            default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        return sp

    def _scope(sp, *, single: bool = True, joint: bool = False):
        """挂库作用域选项（v1.29/v1.30）：`--repo` 单库 / `--repos a,b` 联查。

        缺省不传 = 后端语义（读命令取**活动库**；列表命令不限定）。
        """
        if single:
            sp.add_argument("--repo", metavar="ID", default="",
                            help="书目作用域：指定 repo_id（缺省 = 活动库）")
        if joint:
            sp.add_argument("--repos", metavar="A,B", default="",
                            help="联查多个书目（逗号分隔；与 --repo 择一使用）")

    # ── 系统状态 ──
    sp = _sp("status", "查看系统健康状态")
    sp.set_defaults(handler=commands.cmd_status)

    sp = _sp("state-key", "显示状态校验密钥")
    sp.set_defaults(handler=commands.cmd_state_key)

    # ── 事件管理 ──
    sp = _sp("ingest", "写入事件")
    sp.add_argument("content", help="事件内容")
    sp.add_argument("--type", default="interaction", choices=["interaction", "data", "source"],
                    help="事件类型 (默认: interaction)")
    _scope(sp)
    sp.set_defaults(handler=commands.cmd_ingest)

    sp = _sp("events", "分页事件列表")
    sp.add_argument("--type", help="按类型筛选 (interaction/data/source)")
    sp.add_argument("--status", help="按状态筛选 (raw/indexed/linked/failed/skipped)")
    sp.add_argument("--limit", type=int, default=20, help="每页数量 (默认: 20)")
    sp.add_argument("--offset", type=int, default=0, help="偏移量 (默认: 0)")
    _scope(sp, joint=True)
    sp.set_defaults(handler=commands.cmd_events)

    sp = _sp("event", "事件操作: view / edit / retry / skip / unskip / delete")
    sp.add_argument("action", nargs="?", default="view",
                    choices=["view", "edit", "retry", "skip", "unskip", "delete"],
                    help="操作类型 (默认: view)")
    sp.add_argument("event_id", help="事件 ID")
    sp.add_argument("content", nargs="?", default="", help="新内容 (仅 edit)")
    _scope(sp)
    sp.set_defaults(handler=commands.cmd_event)

    # ── 节点管理 ──
    sp = _sp("nodes", "分页节点列表")
    sp.add_argument("--type", help="按类型筛选 (system/interaction/data)")
    sp.add_argument("--limit", type=int, default=20, help="每页数量 (默认: 20)")
    sp.add_argument("--offset", type=int, default=0, help="偏移量 (默认: 0)")
    _scope(sp, joint=True)
    sp.set_defaults(handler=commands.cmd_nodes)

    sp = _sp("node", "节点操作: view / create / edit / delete")
    sp.add_argument("node_id", nargs="?", default="", help="节点 ID")
    sp.add_argument("content", nargs="?", default="", help="新内容 (仅 edit)")
    sp.add_argument("--action", default="",
                    choices=["view", "create", "edit", "delete"],
                    help="操作类型 (默认: 自动推断)")
    sp.add_argument("--title", help="节点标题 (仅 create)")
    sp.add_argument("--content", dest="create_content", help="节点内容 (仅 create)")
    sp.add_argument("--type", dest="node_type", default="data",
                    choices=["system", "interaction", "data"], help="节点类型 (仅 create)")
    sp.add_argument("--event", help="源事件 ID (仅 create)")
    sp.add_argument("--force", action="store_true", help="强制删除 (仅 delete)")
    _scope(sp)
    sp.set_defaults(handler=commands.cmd_node)

    # ── 边管理 ──
    sp = _sp("edge", "边操作: create / delete")
    sp.add_argument("action", nargs="?", default="create",
                    choices=["create", "delete"], help="操作类型 (默认: create)")
    sp.add_argument("--source", required=True, help="源节点 ID")
    sp.add_argument("--target", required=True, help="目标节点 ID")
    sp.add_argument("--relation", help="关系描述 (仅 create)")
    sp.add_argument("--event", help="证据事件 ID (仅 create)")
    sp.set_defaults(handler=commands.cmd_edge)

    sp = _sp("edges", "边列表（GET /edges，v1.37：一次取全，支持筛选与库作用域）")
    sp.add_argument("--node", metavar="ID", default="", help="只看与该节点相连的边（两侧命中）")
    sp.add_argument("--source", metavar="ID", default="", help="按起点筛选")
    sp.add_argument("--target", metavar="ID", default="", help="按终点筛选")
    sp.add_argument("--relation", metavar="R", default="", help="按关系短语筛选（精确匹配）")
    sp.add_argument("--limit", type=int, default=200, help="每页数量 (默认: 200，上限 5000)")
    sp.add_argument("--offset", type=int, default=0, help="偏移量 (默认: 0)")
    _scope(sp, joint=True)
    sp.set_defaults(handler=commands.cmd_edges)

    # ── 检索与反馈 ──
    sp = _sp("search", "混合检索")
    sp.add_argument("query", help="搜索关键词")
    sp.add_argument("--type", default="all",
                    choices=["all", "interaction", "data", "system"],
                    help="来源类型过滤 (默认: all)")
    sp.add_argument("--hops", type=int, default=2, help="图扩散跳数 (默认: 2)")
    sp.add_argument("--limit", type=int, default=20, help="每页数量 (默认: 20)")
    sp.add_argument("--offset", type=int, default=0, help="偏移量 (默认: 0)")
    _scope(sp, single=False, joint=True)
    sp.set_defaults(handler=commands.cmd_search)

    sp = _sp("feedback", "检索结果反馈")
    sp.add_argument("result_id", help="结果 ID (node_id)")
    group = sp.add_mutually_exclusive_group(required=True)
    group.add_argument("--accept", action="store_true", help="采纳结果")
    group.add_argument("--reject", action="store_true", help="拒绝结果")
    _scope(sp)
    sp.set_defaults(handler=commands.cmd_feedback)

    # ── 配置管理 ──
    sp = _sp("config", "配置管理: list / set / probe")
    sp.add_argument("action", nargs="?", default="list",
                    choices=["list", "set", "probe"], help="操作类型 (默认: list)")
    sp.add_argument("key", nargs="?", default="",
                    help="配置项名称 (set) / 提供商名 (probe)")
    sp.add_argument("value", nargs="?", default="", help="配置项值 (仅 set)")
    sp.add_argument("--base-url", dest="base_url", default="",
                    help="探测用的地址 (仅 probe，缺省用已登记的)")
    sp.add_argument("--api-key", dest="api_key", default="",
                    help="探测用的密钥 (仅 probe，缺省用已登记的)")
    sp.set_defaults(handler=commands.cmd_config)

    # ── 图谱管理 ──
    sp = _sp("graph", "图谱管理: clear（v1.42 起清空前自动留档整图，可在 trash 恢复）")
    sp.add_argument("action", nargs="?", default="clear",
                    choices=["clear"], help="操作类型 (默认: clear)")
    sp.set_defaults(handler=commands.cmd_graph_clear)

    # ── 库管理（v1.29+，11 个端点）──
    sp = _sp("repo", "库管理: list / show / create / update / delete / activate / "
                     "refresh / generate / adopt / rebuild / purge")
    sp.add_argument("action", nargs="?", default="list",
                    choices=["list", "show", "create", "update", "delete", "activate",
                             "refresh", "generate", "adopt", "rebuild", "purge"],
                    help="操作类型 (默认: list)")
    sp.add_argument("repo_id", nargs="?", default="",
                    help="书目 id (show/update/delete/activate/refresh/generate/purge)")
    sp.add_argument("--name", default="", help="名称 (create/update)")
    sp.add_argument("--note", default="", help="备注 (create/update)")
    sp.add_argument("--group", default="", help="分组/书架名 (create/update)")
    sp.add_argument("--root", default="", help="目录 (create external / adopt / update 重指向)")
    sp.add_argument("--kind", default="managed", choices=["managed", "external"],
                    help="建库类型 (仅 create，默认 managed)")
    sp.add_argument("--managed", default=None,
                    help="受管开关 (仅 update：true/false；false = 休眠不加载)")
    sp.add_argument("--no-missing", dest="no_missing", action="store_true",
                    help="收养时缺件即报错（不补空文件）(仅 adopt)")
    sp.add_argument("--yes", action="store_true",
                    help="确认危险操作 (仅 purge：会删除该库的 memory.db 与 graph.json)")
    sp.set_defaults(handler=commands.cmd_repo)

    # ── 存储维护（v1.30）──
    sp = _sp("maintenance", "存储维护: backup / backups / verify / ops / checkpoint")
    sp.add_argument("action", nargs="?", default="verify",
                    choices=["backup", "backups", "verify", "ops", "checkpoint"],
                    help="操作类型 (默认: verify)")
    sp.add_argument("--note", default="", help="备份备注 (仅 backup)")
    sp.add_argument("--limit", type=int, default=100, help="每页数量 (仅 ops，默认: 100)")
    sp.add_argument("--offset", type=int, default=0, help="偏移量 (仅 ops)")
    _scope(sp)
    sp.set_defaults(handler=commands.cmd_maintenance)

    # ── 本地日志与回收站（v1.31）──
    sp = _sp("logs", "翻看本地日志尾部（backend-*.log / frontend-*.log）")
    sp.add_argument("--kind", default="backend", choices=["backend", "frontend"],
                    help="日志通道 (默认: backend)")
    sp.add_argument("--date", default="", help="日期 YYYY-MM-DD (缺省 = 该通道最新一天)")
    sp.add_argument("--level", default="", help="按级别词过滤（大小写不敏感）")
    sp.add_argument("--keyword", default="", help="按子串过滤")
    sp.add_argument("--tail", type=int, default=200, help="取最新 N 行 (默认: 200，上限 2000)")
    sp.set_defaults(handler=commands.cmd_logs)

    sp = _sp("trash", "回收站: list / restore（kind=graph 为整图留档，合并式恢复）")
    sp.add_argument("action", nargs="?", default="list", choices=["list", "restore"],
                    help="操作类型 (默认: list)")
    sp.add_argument("item_id", nargs="?", default="", help="留档 id (仅 restore)")
    sp.add_argument("--kind", default="event", choices=["event", "node", "graph"],
                    help="留档类型 (仅 restore，默认: event；graph = 清空图层时留的整图，合并式补回)")
    _scope(sp)
    sp.set_defaults(handler=commands.cmd_trash)

    # ── Agent 运维 ──
    sp = _sp("agent", "Agent 运维: logs / compensate / maintain")
    sp.add_argument("action", nargs="?", default="logs",
                    choices=["logs", "compensate", "maintain"],
                    help="操作类型 (默认: logs)")
    sp.add_argument("--limit", type=int, default=50, help="日志条数 (仅 logs，默认: 50)")
    sp.add_argument("--full", action="store_true",
                    help="日志取全文 (仅 logs；后端 AGENT_LOGS_FULL=false 时忽略)")
    sp.add_argument("--mode", default="update", choices=["update", "compress"],
                    help="维护模式 (仅 maintain：update 两阶段 / compress 删繁就简)")
    _scope(sp)
    sp.set_defaults(handler=commands.cmd_agent)

    # ── Shell ──
    sp = _sp("shell", "进入交互式 Shell 模式")
    sp.set_defaults(handler=None)

    return sub


def main():
    """主入口。"""
    # 无参数 → 进入 Shell
    if len(sys.argv) == 1:
        run_shell()
        return

    # 检查 -h/--help：仅在无子命令时打印全局帮助；
    # 子命令的 -h（如 dpim ingest -h）由 argparse 子解析器处理，显示对应命令详情
    if sys.argv[1] in ("-h", "--help"):
        print_global_help()
        return

    parser = _parser()
    _build_subparsers(parser)

    # 解析命令行
    args = parser.parse_args()

    # 注入全局选项
    if not hasattr(args, "api") or not args.api:
        args.api = cli_config.get("api_url")
    if not hasattr(args, "format") or not args.format:
        args.format = cli_config.get("format")

    # 分发
    handler = getattr(args, "handler", None)
    if handler is None:
        # shell 命令
        run_shell(api_url=args.api, output_format=getattr(args, "format", "table"))
        return

    # 补全 node / edge 的参数兼容
    if args.command == "node":
        if args.create_content:
            args.content = args.create_content
        if args.node_type:
            args.type = args.node_type

    handler(args)


def print_global_help():
    """打印全局帮助。"""
    parser = _parser()
    parser.print_help()
    print("""\n可用命令:
  status            查看系统健康状态
  state-key         显示状态校验密钥
  ingest            写入事件
  events            分页事件列表
  event             事件操作 (view/edit/retry/skip/unskip/delete)
  nodes             分页节点列表
  node              节点操作 (view/create/edit/delete)
  edge              边操作 (create/delete)
  edges             边列表 (GET /edges，支持 --node/--source/--target/--relation)
  search            混合检索
  feedback          检索结果反馈
  config            配置管理 (list/set/probe)
  graph             图谱管理
  repo              库管理 (list/show/create/update/delete/activate/refresh/
                    generate/adopt/rebuild/purge)
  maintenance       存储维护 (backup/backups/verify/ops/checkpoint)
  logs              翻看本地日志尾部
  trash             回收站 (list/restore)
  agent             Agent 运维 (logs/compensate/maintain)
  shell             进入交互式 Shell

库作用域（v1.29/v1.30）：读命令支持 --repo <id>（缺省 = 活动库）；
列表/检索类还支持 --repos a,b（联查多个书目）。
使用 dpim <command> -h 查看命令详细用法。""")


if __name__ == "__main__":
    main()
