"""FastAPI 应用，15 个 REST 端点"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from controller.compensator import Compensator
from controller.orchestrator import Orchestrator
from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import (
    CreateEdgeRequest,
    CreateNodeRequest,
    DeleteNodeRequest,
    EdgeInfo,
    EventListItem,
    EventListResponse,
    FeedbackRequest,
    GraphEdge,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    ModifyEventRequest,
    ModifyEventStatusRequest,
    ModifyNodeRequest,
    NodeDetailResponse,
    NodeListItem,
    NodeListResponse,
    SearchRequest,
    SearchResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    StateHashResponse,
)
from core.search import search as hybrid_search
from core.state import ai_state, get_key, refresh_key


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
    refresh_key()
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
    refresh_key()
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
    refresh_key()
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
    refresh_key()
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
    refresh_key()
    return _ok(event_id=event_id, new_status=new, message="Status updated")


@app.put("/events/{event_id}")
async def modify_event(event_id: str, body: ModifyEventRequest):
    es, gs = _stores()
    ok = await es.update_content(event_id, body.content)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found")
    refresh_key()
    return _ok(event_id=event_id, message="Event content updated")


@app.post("/edges")
async def create_edge(body: CreateEdgeRequest):
    es, gs = _stores()
    # 检查两端节点存在
    src = gs.get_node(body.source)
    if src is None:
        raise HTTPException(status_code=404, detail="Source node not found")
    tgt = gs.get_node(body.target)
    if tgt is None:
        raise HTTPException(status_code=404, detail="Target node not found")
    gs.add_edge(GraphEdge(
        source=body.source,
        target=body.target,
        relation=body.relation,
        evidence_event_id=body.evidence_event_id or "",
    ))
    await gs.flush()
    refresh_key()
    return _ok(message="Edge created")


@app.delete("/edges")
async def delete_edge(source: str, target: str):
    es, gs = _stores()
    ok = gs.remove_edge(source, target)
    if not ok:
        raise HTTPException(status_code=404, detail="Edge not found")
    await gs.flush()
    refresh_key()
    return _ok(message="Edge deleted")


@app.post("/nodes")
async def create_node(body: CreateNodeRequest):
    import uuid
    from core.models import GraphNode, SourceRef, NodeMetadata
    es, gs = _stores()
    node_id = uuid.uuid4().hex[:16]

    source_refs = []
    if body.source_event_id:
        source_refs.append(SourceRef(
            event_id=body.source_event_id,
            valid=True,
            hash="",
        ))

    node = GraphNode(
        node_id=node_id,
        title=body.title,
        content=body.content or body.title,
        node_type=body.node_type,
        source_refs=source_refs,
        confidence=0.7,
        metadata=NodeMetadata(evidence_quote=body.content or body.title, tags=[]),
    )
    gs.add_node(node)
    await gs.flush()
    refresh_key()
    return _ok(node_id=node_id, message="Node created")


@app.delete("/graph")
async def clear_graph():
    es, gs = _stores()
    gs.clear_all()
    await gs.flush()
    refresh_key()
    return _ok(message="Graph cleared")


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


# ── dpim-webui 新增端点 ────────────────────

@app.get("/state-hash", response_model=StateHashResponse)
async def state_hash():
    es, gs = _stores()
    changed_at = await es.last_event_at()
    return StateHashResponse(hash=get_key(), changed_at=changed_at or "")


@app.get("/events", response_model=EventListResponse)
async def list_events(
    status: str | None = None,
    type: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    es, gs = _stores()
    items, total = await es.list_events(
        status=status, event_type=type, limit=min(limit, 100), offset=offset,
    )
    return EventListResponse(
        items=[EventListItem(**e) for e in items],
        total=total, limit=limit, offset=offset,
    )


@app.get("/events/{event_id}")
async def get_event(event_id: str):
    es, gs = _stores()
    event = await es.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.get("/nodes", response_model=NodeListResponse)
async def list_nodes(
    type: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    es, gs = _stores()
    all_nodes = gs.list_nodes(node_type=type)
    total = len(all_nodes)
    sliced = all_nodes[offset:offset + limit]
    return NodeListResponse(
        items=[NodeListItem(**n) for n in sliced],
        total=total, limit=limit, offset=offset,
    )


@app.get("/nodes/{node_id}", response_model=NodeDetailResponse)
async def get_node(node_id: str):
    es, gs = _stores()
    node = gs.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    edges = gs.list_edges(node_id=node_id)
    return NodeDetailResponse(
        node_id=node.node_id,
        title=node.title,
        content=node.content,
        node_type=node.node_type.value,
        source_refs=[
            {"event_id": sr.event_id, "valid": sr.valid, "hash": sr.hash}
            for sr in node.source_refs
        ],
        confidence=node.confidence,
        metadata=node.metadata.model_dump() if hasattr(node.metadata, "model_dump") else dict(node.metadata),
        edges=[EdgeInfo(**e) for e in edges],
    )


@app.get("/settings", response_model=SettingsResponse)
async def get_settings():
    return SettingsResponse(
        memory_db_path=settings.memory_db_path,
        graph_json_path=settings.graph_json_path,
        llm_base_url=settings.llm_base_url,
        llm_api_key=settings.llm_api_key,
        llm_model_name=settings.llm_model_name,
        llm_timeout=settings.llm_timeout,
        max_graph_hops=settings.max_graph_hops,
        rrf_k=settings.rrf_k,
        jaccard_threshold=settings.jaccard_threshold,
        health_check_interval=settings.health_check_interval,
        compensate_batch_size=settings.compensate_batch_size,
        log_level=settings.log_level,
    )


@app.put("/settings")
async def update_settings(body: SettingsUpdateRequest):
    for field, value in body.model_dump(exclude_none=True).items():
        if hasattr(settings, field):
            setattr(settings, field, value)
    refresh_key()
    return _ok(message="Settings updated (runtime only, not persisted to .env)")


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
