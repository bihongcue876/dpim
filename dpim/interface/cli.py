"""Typer CLI 管理命令 — 无 Agent 模式也支持完整基本功能"""

import asyncio
import json

import typer

from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import SearchRequest
from core.search import search as hybrid_search



cli = typer.Typer()


async def _stores():
    db = Database()
    await db.connect()
    es = EventStore(db)
    gs = GraphStore(db)
    await gs.load()
    return db, es, gs


@cli.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """启动 FastAPI 服务"""
    import uvicorn
    uvicorn.run("interface.api:app", host=host, port=port, reload=reload)


@cli.command()
def ingest(content: str, event_type: str = "auto"):
    """写入一条原始事件"""
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
        event = await es.get(event_id)
        if not event:
            typer.echo(f"Event {event_id} not found")
            return
        refs = event.get("graph_refs", [])
        for nid in refs:
            node = gs.get_node(nid)
            if node is None:
                continue
            gs.invalidate_source_ref(event_id)
            has_valid = any(sr.valid for sr in node.source_refs if sr.event_id != event_id)
            if not has_valid:
                if node.node_type.value in ("system", "data"):
                    typer.echo(
                        f"Warning: node {nid} ({node.node_type.value}) protected,"
                        " keeping event"
                    )
                    return
                gs.remove_node(nid)
                await gs.delete_node_fts(nid)
        await es.delete(event_id)
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
    """显示存储文件路径"""
    typer.echo(f"SQLite DB:  {settings.memory_db_path}")
    typer.echo(f"Graph JSON: {settings.graph_json_path}")
    typer.echo("")
    typer.echo("提示：这两个文件可人工编辑，重新启动后生效。")
    typer.echo("graph.json 为 JSON 格式，支持任意文本编辑器修改。")
    typer.echo("memory.db 为标准 SQLite 数据库，可用 sqlite3 / DB Browser 打开。")
