"""FastAPI 应用，8 个 REST 端点"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from controller.compensator import Compensator
from controller.orchestrator import Orchestrator
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import (
    DeleteNodeRequest,
    FeedbackRequest,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    ModifyEventStatusRequest,
    ModifyNodeRequest,
    SearchRequest,
    SearchResponse,
)
from core.search import search as hybrid_search
from core.state import ai_state


def _ok(**extra: str) -> dict[str, str]:
    """统一成功响应信封：所有简单端点返回 status=ok + message + 可选字段。"""
    return {"status": "ok", "message": "ok", **extra}


db: Database | None = None
event_store: EventStore | None = None
graph_store: GraphStore | None = None
orchestrator: Orchestrator | None = None
compensator: Compensator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, event_store, graph_store, orchestrator, compensator
    db = Database()
    await db.connect()
    event_store = EventStore(db)
    graph_store = GraphStore(db)
    await graph_store.load()
    orchestrator = Orchestrator(db, event_store, graph_store)
    orchestrator.start()
    compensator = Compensator(event_store, graph_store, orchestrator.enqueue)
    compensator.start()
    yield
    if compensator:
        await compensator.stop()
    if orchestrator:
        await orchestrator.stop()
    if graph_store and graph_store.dirty:
        await graph_store.save()
        await graph_store.flush()
    if db:
        await db.close()


app = FastAPI(title="DPIM", version="0.1.0", lifespan=lifespan)


def _stores():
    if not event_store or not graph_store:
        raise HTTPException(status_code=503, detail="Storage not initialized")
    return event_store, graph_store


@app.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest):
    es, gs = _stores()
    eid, status = await es.insert_event(body.content, body.event_type)
    return IngestResponse(event_id=eid, status=status, message="Event ingested")


@app.delete("/events/{event_id}")
async def delete_event(event_id: str):
    es, gs = _stores()
    result = await es.delete_with_protection(event_id, gs)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Event not found")
    if result["status"] == "protected":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete event: node {result['node_id']} ({result['node_type']})"
                   " would lose all source references",
        )
    return _ok(message="Event deleted")


@app.delete("/nodes/{node_id}")
async def delete_node(node_id: str, body: DeleteNodeRequest = DeleteNodeRequest()):
    es, gs = _stores()
    node = gs.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    valid_refs = [sr for sr in node.source_refs if sr.valid]
    if valid_refs and not body.force:
        raise HTTPException(
            status_code=409,
            detail=f"Node has {len(valid_refs)} valid source refs. Use force=true to override",
        )
    gs.remove_node(node_id)
    await gs.delete_node_fts(node_id)
    return _ok(message="Node deleted")


@app.put("/nodes/{node_id}")
async def modify_node(node_id: str, body: ModifyNodeRequest):
    es, gs = _stores()
    node = gs.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.node_type.value == "system":
        raise HTTPException(status_code=403, detail="System nodes cannot be modified")
    node.content = body.content
    node.confidence = 0.7
    gs.graph.nodes[node_id]["data"] = node
    await gs.upsert_node_fts(node_id, node.title, node.content)
    if gs.dirty:
        await gs.save()
    return _ok(node_id=node_id, message="Node updated")


@app.put("/events/{event_id}/status")
async def modify_event_status(event_id: str, body: ModifyEventStatusRequest):
    es, gs = _stores()
    event = await es.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    allowed = {("failed", "indexed"), ("skipped", "indexed"), ("indexed", "skipped"),
               ("skipped", "indexed"), ("failed", "skipped"), ("skipped", "failed")}
    current = event["status"]
    new = body.status.value
    if (current, new) not in allowed and current != "indexed" and new != "linked":
        raise HTTPException(
            status_code=400,
            detail=f"Status transition {current} -> {new} not allowed",
        )
    await es.update_status(event_id, new)
    return _ok(event_id=event_id, new_status=new, message="Status updated")


@app.post("/query", response_model=SearchResponse)
async def query(body: SearchRequest):
    es, gs = _stores()
    return await hybrid_search(body, es, gs, degraded=not ai_state.available)


@app.post("/feedback")
async def feedback(body: FeedbackRequest):
    es, gs = _stores()
    # result_id is a node_id or event_id
    node = gs.get_node(body.result_id)
    if node:
        if node.node_type.value in ("system", "data"):
            return _ok(message="System/data nodes not affected by feedback")
        delta = 0.01 if body.accepted else -0.02
        node.confidence = max(0.1, min(1.0, node.confidence + delta))
        gs.graph.nodes[body.result_id]["data"] = node
    return _ok(message="Feedback recorded")


@app.get("/health", response_model=HealthResponse)
async def health():
    es, gs = _stores()
    total_events = await es.total_events()
    status_counts = await es.count_by_status()
    total_nodes = gs.total_nodes()
    node_counts = gs.node_counts_by_type()
    last = await es.last_event_at()
    return HealthResponse(
        status="ok" if ai_state.available else "degraded",
        ai_available=ai_state.available,
        layers={
            "event_line": {
                "total_events": total_events,
                **status_counts,
            },
            "knowledge_graph": {
                "total_nodes": total_nodes,
                **node_counts,
            },
        },
        last_event_at=last or "",
    )
