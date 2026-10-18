"""Typer CLI 管理命令 — 无 Agent 模式也支持完整基本功能"""

import asyncio
import json
import shutil
from pathlib import Path

import typer

from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.lockfile import SingleInstanceLock
from core.logging_setup import (
    BACKEND,
    list_log_files,
    read_log_lines,
    setup_file_logging,
)
from core.maintenance import create_backup, list_backups, verify_storage
from core.models import SearchRequest
from core.search import search as hybrid_search
from core.trash import list_archived, load_archived, trash_root

cli = typer.Typer()

# 进程存活期间持有的跨进程锁（退出时由内核释放，无需显式清理）
_HELD_LOCKS: list[SingleInstanceLock] = []


@cli.callback()
def _bootstrap():
    """DPIM 本地管理 CLI（直连存储层；本机日志自动落盘）。"""
    setup_file_logging()


async def _stores():
    # 跨进程互斥：本地 CLI 直连存储，必须与运行中的 serve 互斥，
    # 否则两个进程整文件改写 graph.json 会互相覆盖（丢更新）
    lock = SingleInstanceLock(settings.memory_db_path + ".lock")
    if not lock.acquire():
        typer.echo("该库正被另一个进程写入（通常是运行中的 serve）。")
        typer.echo("请改用 REST 客户端（dpimCLI / WebUI），或先停掉那个进程。")
        raise typer.Exit(1)
    _HELD_LOCKS.append(lock)  # 进程存活期间持有；退出由内核自动释放
    db = Database()
    await db.connect()
    es = EventStore(db)
    gs = GraphStore(db)
    await gs.load()
    await gs.reconcile(es)
    await gs.flush()
    return db, es, gs


@cli.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """启动 FastAPI 服务"""
    import uvicorn
    uvicorn.run("interface.api:app", host=host, port=port, reload=reload)


@cli.command()
def ingest(content: str, event_type: str = typer.Option("interaction", help="事件类型：interaction / data / source")):
    """写入一条原始事件"""
    from core.commands import parse_command, usage_text

    if parse_command(content) is not None:
        # 对话指令需经运行中的服务执行（WebUI / dpimCLI / POST /ingest），
        # 本命令直写存储层无法触发管线，直接落库会污染事件日志
        typer.echo("检测到对话指令：请通过运行中的服务使用（WebUI 信息传入 / dpimCLI ingest）。")
        typer.echo(usage_text())
        raise typer.Exit(1)

    async def _run():
        db, es, gs = await _stores()
        eid, status = await es.insert_event(content, event_type)
        await db.close()
        typer.echo(f"Event {eid} ingested, status={status}")
    asyncio.run(_run())


@cli.command()
def query(text: str, limit: int = 10):
    """检索信息"""
    async def _run():
        db, es, gs = await _stores()
        req = SearchRequest(query=text, limit=limit)
        resp = await hybrid_search(req, es, gs)
        await db.close()
        if not resp.results:
            typer.echo("No results")
            return
        for r in resp.results:
            typer.echo(f"[{r.score:.3f}] {r.title} ({r.source_type})")
            typer.echo(f"  {r.snippet[:100]}...")
    asyncio.run(_run())


@cli.command()
def status():
    """查看系统状态"""
    async def _run():
        db, es, gs = await _stores()
        total = await es.total_events()
        counts = await es.count_by_status()
        nodes = gs.total_nodes()
        node_types = gs.node_counts_by_type()
        last = await es.last_event_at()
        await db.close()
        typer.echo(f"Events: {total} (raw={counts['raw']} indexed={counts['indexed']}"
                   f" linked={counts['linked']} failed={counts['failed']}"
                   f" skipped={counts['skipped']})")
        typer.echo(f"Nodes: {nodes} (system={node_types['system']} "
                   f"interaction={node_types['interaction']} data={node_types['data']})")
        typer.echo(f"Last event: {last or 'N/A'}")
    asyncio.run(_run())


@cli.command()
def delete_event(event_id: str):
    """删除事件"""
    async def _run():
        db, es, gs = await _stores()
        # 复用存储层删除保护逻辑（预检 + 源证失效 + interaction 节点清理）
        result = await es.delete_with_protection(event_id, gs)
        if result["status"] == "not_found":
            typer.echo(f"Event {event_id} not found")
        elif result["status"] == "protected":
            typer.echo(
                f"Warning: node {result.get('node_id')} "
                f"({result.get('node_type')}) protected, keeping event"
            )
        else:
            typer.echo(f"Event {event_id} deleted")
        if gs.dirty:
            await gs.save()
        await db.close()
    asyncio.run(_run())


@cli.command()
def view_event(event_id: str):
    """查看事件详情"""
    async def _run():
        db, es, gs = await _stores()
        ev = await es.get(event_id)
        await db.close()
        if not ev:
            typer.echo("Event not found")
            raise typer.Exit(1)
        typer.echo(f"ID:      {ev['event_id']}")
        typer.echo(f"Created: {ev['created_at']}")
        typer.echo(f"Type:    {ev['event_type']}")
        typer.echo(f"Status:  {ev['status']}")
        typer.echo(f"Hash:    {ev['content_hash']}")
        typer.echo(f"Refs:    {ev['graph_refs']}")
        typer.echo(f"Content: {ev['raw_content'][:500]}")
    asyncio.run(_run())


@cli.command()
def list_events(status: str = "", limit: int = 50):
    """列出事件（可按状态筛选）"""
    async def _run():
        db, es, gs = await _stores()
        if status:
            rows = await es.list_by_status(status)
        else:
            rows = []
            for s in ("raw", "indexed", "linked", "failed", "skipped"):
                rows.extend(await es.list_by_status(s))
        await db.close()
        rows = rows[:limit]
        if not rows:
            typer.echo("No events")
            return
        for r in rows:
            refs_raw = r.get("graph_refs", "[]")
            if isinstance(refs_raw, str):
                try:
                    refs = json.loads(refs_raw)
                except (json.JSONDecodeError, TypeError):
                    refs = []
            else:
                refs = refs_raw
            typer.echo(f"{r['event_id'][:24]:24s} {r['status']:8s} "
                       f"{r['event_type']:12s} refs={json.dumps(refs)}")
    asyncio.run(_run())


@cli.command()
def list_nodes(limit: int = 50):
    """列出图节点"""
    async def _run():
        db, es, gs = await _stores()
        await db.close()
        nids = list(gs.graph.nodes())
        if not nids:
            typer.echo("No nodes")
            return
        for nid in nids[:limit]:
            node = gs.get_node(nid)
            if node is None:
                continue
            refs = len(node.source_refs)
            typer.echo(f"{nid:24s} {node.node_type.value:12s} "
                       f"conf={node.confidence:.2f} refs={refs}  {node.title[:30]}")
    asyncio.run(_run())


@cli.command()
def storage_path():
    """显示存储文件与日志路径"""
    typer.echo(f"SQLite DB:  {settings.memory_db_path}")
    typer.echo(f"Graph JSON: {settings.graph_json_path}")
    typer.echo(f"日志目录:   {settings.log_dir}")
    typer.echo("")
    typer.echo("提示：这两个存储文件可人工编辑，重新启动后生效。")
    typer.echo("graph.json 为 JSON 格式，支持任意文本编辑器修改。")
    typer.echo("memory.db 为标准 SQLite 数据库，可用 sqlite3 / DB Browser 打开。")
    typer.echo("日志为纯文本（前后端分文件），直接打开即可翻看。")


@cli.command()
def logs(
    stream: str = typer.Option(BACKEND, help="日志通道：backend / frontend / all"),
    day: str = typer.Option("", help="只看某天（YYYY-MM-DD；空 = 全部）"),
    level: str = typer.Option("", help="只看某级别（INFO / WARNING / ERROR 等）"),
    grep: str = typer.Option("", "--grep", help="关键词过滤"),
    tail: int = typer.Option(50, help="显示尾部行数"),
    list_files: bool = typer.Option(False, "--list", help="只列出日志文件，不读内容"),
):
    """查看本地日志（前后端分文件，按天轮转）"""
    if list_files:
        files = list_log_files()
        if not files:
            typer.echo(f"日志目录暂无文件：{settings.log_dir}")
            return
        typer.echo(f"日志目录：{settings.log_dir}")
        for item in files:
            typer.echo(
                f"  {item['name']:34s} {item['size']:>9d} B  {item['stream']}/{item['day']}"
            )
        return
    lines = read_log_lines(
        stream=stream,
        day=day or None,
        level=level or None,
        keyword=grep or None,
        limit=tail,
    )
    if not lines:
        typer.echo(
            f"没有匹配的日志（目录={settings.log_dir} 通道={stream}"
            f" 天={day or '全部'} 级别={level or '全部'} 关键词={grep or '无'}）"
        )
        return
    for line in lines:
        typer.echo(line)


# ── 存储维护（P4）：备份 / 校验 / 恢复 / 回收站 ──────────────────────────────


@cli.command()
def backup(note: str = ""):
    """整库备份（SQLite 在线副本 + graph.json + 清单）"""
    async def _run():
        db, es, gs = await _stores()
        result = await create_backup(db, gs, note=note)
        await db.close()
        m = result["manifest"]
        typer.echo(f"备份目录: {result['backup_dir']}")
        typer.echo(f"  事件 {m['total_events']} / 节点 {m['total_nodes']} / 边 {m['total_edges']}"
                   f" / 操作日志 {m['graph_ops']}")
        typer.echo(f"  db {m['db_bytes']} B / json {m['json_bytes']} B"
                   f" / 清理旧备份 {result['pruned']} 份")
    asyncio.run(_run())


@cli.command()
def backups():
    """列出整库备份"""
    rows = list_backups(settings.memory_db_path)
    if not rows:
        typer.echo("暂无备份")
        return
    for item in rows:
        m = item["manifest"]
        typer.echo(f"{item['stamp']:20s} {item['bytes']:>10d} B  "
                   f"事件 {m.get('total_events', '?')} / 节点 {m.get('total_nodes', '?')}"
                   f"  {m.get('note', '')}")


@cli.command()
def verify():
    """存储一致性校验（只读）"""
    async def _run():
        db, es, gs = await _stores()
        result = await verify_storage(db, gs)
        await db.close()
        for check in result["checks"]:
            mark = "OK  " if check["ok"] else "FAIL"
            typer.echo(f"[{mark}] {check['name']:28s} {check['detail']}")
        typer.echo(f"总体: {'通过' if result['ok'] else '有问题'}")
        typer.echo(f"容量: {result['sizes']}")
    asyncio.run(_run())


@cli.command()
def restore(stamp: str, yes: bool = typer.Option(False, "--yes", help="确认执行（会覆盖当前库文件）")):
    """从整库备份恢复（覆盖前自动给当前状态做一次安全备份）"""
    if not yes:
        typer.echo("恢复会覆盖当前 memory.db 与 graph.json；确认请加 --yes。")
        raise typer.Exit(1)

    async def _run():
        lock = SingleInstanceLock(settings.memory_db_path + ".lock")
        if not lock.acquire():
            typer.echo("该库正被另一个进程写入（通常是 serve），请先停掉服务再恢复。")
            raise typer.Exit(1)
        _HELD_LOCKS.append(lock)
        available = {item["stamp"]: item for item in list_backups(settings.memory_db_path)}
        target = available.get(stamp)
        if target is None:
            typer.echo(f"未找到备份 {stamp}；可用：{', '.join(available) or '（无）'}")
            raise typer.Exit(1)
        # 1) 先给当前状态做安全备份（恢复错了还能退回来）
        db = Database()
        await db.connect()
        gs = GraphStore(db)
        await gs.load()
        safety = await create_backup(db, gs, note=f"restore 前安全备份（目标 {stamp}）")
        await db.close()
        typer.echo(f"已先做安全备份: {safety['stamp']}")
        # 2) 覆盖库文件（先清 WAL/SHM：陈旧 WAL 会让新主库读出错乱数据）
        src = Path(target["path"])
        db_name = Path(settings.memory_db_path).name
        json_name = Path(settings.graph_json_path).name
        for suffix in ("-wal", "-shm"):
            stale = Path(str(settings.memory_db_path) + suffix)
            if stale.exists():
                stale.unlink()
        shutil.copy2(src / db_name, settings.memory_db_path)
        if (src / json_name).exists():
            shutil.copy2(src / json_name, settings.graph_json_path)
        typer.echo(f"已从备份 {stamp} 恢复；请重启服务使其生效。")

    asyncio.run(_run())


@cli.command()
def trash_list():
    """列出回收站留档（删除前留档的事件/节点）"""
    rows = list_archived(settings.memory_db_path)
    if not rows:
        typer.echo(f"回收站为空（{trash_root(settings.memory_db_path)}）")
        return
    for item in rows:
        typer.echo(f"{item['archived_at'][:19]:20s} {item['kind']:7s} "
                   f"{item['item_id']:28s} {item['bytes']:>8d} B")


@cli.command()
def trash_restore(event_id: str):
    """从回收站恢复一条事件（按原 event_id 入库，保留图节点源证对应关系）"""
    async def _run():
        archived = load_archived(settings.memory_db_path, "events", event_id)
        if archived is None:
            typer.echo(f"回收站中没有事件 {event_id}")
            raise typer.Exit(1)
        db, es, gs = await _stores()
        ok = await es.restore(archived)
        await db.close()
        typer.echo(f"事件 {event_id} 已恢复" if ok else f"事件 {event_id} 恢复失败")
    asyncio.run(_run())
