"""FastAPI 应用，23 个 REST 端点"""

import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from controller.compensator import Compensator
from controller.orchestrator import Orchestrator
from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.llm import get_llm_logs
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
    QueueMessage,
    SearchRequest,
    SearchResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    StateHashResponse,
)
from core.search import search as hybrid_search
from core.security import (
    mask_provider_secret,
    mask_secret,
    resolve_provider_secret,
    resolve_secret,
)
from core.state import ai_state, get_key, refresh_key

logger = logging.getLogger(__name__)

# 事件状态转换白名单：raw→linked 等绕过管线的转换一律拒绝
ALLOWED_EVENT_TRANSITIONS = {
    ("raw", "indexed"),
    ("indexed", "linked"),
    ("indexed", "failed"),
    ("indexed", "skipped"),
    ("failed", "indexed"),
    ("failed", "skipped"),
    ("skipped", "indexed"),
    ("skipped", "failed"),
}


def _ok(**extra: Any) -> dict[str, Any]:
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
    # 启动自愈：图 source_refs 与事件表现状对齐（悬空/漂移源证置 invalid）
    await graph_store.reconcile(event_store)
    await graph_store.flush()
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


app = FastAPI(title="DPIM", version="0.2.1", lifespan=lifespan)


@app.middleware("http")
async def auth_guard(request, call_next):
    """API 访问认证：DPIM_API_KEY 非空时，所有端点要求 X-API-Key 头匹配。

    默认（DPIM_API_KEY 空）完全放行，本地实验零配置不受影响；
    部署到服务器时设置该环境变量即启用整体保护（含 /settings、/agent/logs 等敏感端点）。
    """
    expected = settings.api_key
    # compare_digest：常数时间比较，防 timing 侧信道逐字节猜测密钥
    if expected and not secrets.compare_digest(
        request.headers.get("X-API-Key", ""), expected
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized: missing or invalid X-API-Key header"},
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return await call_next(request)


def _stores():
    if not event_store or not graph_store:
        raise HTTPException(status_code=503, detail="Storage not initialized")
    return event_store, graph_store


@app.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest):
    es, gs = _stores()
    eid, status = await es.insert_event(body.content, body.event_type.value)
    refresh_key()
    # Agent 管线启用时，入队让管线即时处理（异步，不阻塞写入返回）
    if settings.agent_mode == "pipeline" and ai_state.available and orchestrator:
        await orchestrator.enqueue(
            QueueMessage(
                type="ingest",
                payload={"event_id": eid},
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
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
    if gs.dirty:
        await gs.save()
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
    # update_node 统一标记脏位：修改必须落盘，杜绝静默丢失
    updated = gs.update_node(node_id, content=body.content, confidence=0.7)
    await gs.upsert_node_fts(node_id, updated.title, updated.content)
    await gs.flush()
    refresh_key()
    return _ok(node_id=node_id, message="Node updated")


@app.put("/events/{event_id}/status")
async def modify_event_status(event_id: str, body: ModifyEventStatusRequest):
    es, gs = _stores()
    event = await es.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    current = event["status"]
    new = body.status.value
    if (current, new) not in ALLOWED_EVENT_TRANSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Status transition {current} -> {new} not allowed",
        )
    await es.update_status(event_id, new)
    # 目标为 indexed 且管线可用时入队，让「重试」真正重新走 Agent 管线
    # （对已 indexed 事件 _handle_ingest 会跳过基础索引直接进入管线，幂等安全）
    if (
        new == "indexed"
        and settings.agent_mode == "pipeline"
        and ai_state.available
        and orchestrator
    ):
        await orchestrator.enqueue(
            QueueMessage(
                type="ingest",
                payload={"event_id": event_id},
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
    refresh_key()
    return _ok(event_id=event_id, new_status=new, message="Status updated")


@app.put("/events/{event_id}")
async def modify_event(event_id: str, body: ModifyEventRequest):
    es, gs = _stores()
    ok = await es.update_content(event_id, body.content, gs)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found")
    # 可选类型修订：仅改线层，不联动已生成图节点
    if body.event_type is not None:
        await es.update_type(event_id, body.event_type.value)
    await gs.flush()
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
    from core.models import GraphNode, NodeMetadata, SourceRef
    es, gs = _stores()
    node_id = uuid.uuid4().hex[:16]

    source_refs = []
    if body.source_event_id:
        # SourceRef.hash 与事件 content_hash 一致，保证「hash 供核对」成立
        c_hash = ""
        ev = await es.get(body.source_event_id)
        if ev:
            c_hash = ev["content_hash"]
        source_refs.append(SourceRef(
            event_id=body.source_event_id,
            valid=True,
            hash=c_hash,
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
    # 清空 node_fts：避免旧节点留在全文索引导致检索召回残留
    await gs.rebuild_node_fts()
    await gs.flush()
    refresh_key()
    return _ok(message="Graph cleared")


@app.post("/query", response_model=SearchResponse)
async def query(body: SearchRequest):
    es, gs = _stores()
    if settings.agent_mode == "pipeline" and ai_state.available and orchestrator:
        try:
            return await orchestrator.run_query(body)
        except Exception:
            logger.exception("Query agent pipeline failed, fallback to hybrid search")
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
        new_conf = max(0.1, min(1.0, node.confidence + delta))
        # update_node 标记脏位 + flush 落盘：反馈调整必须持久化
        gs.update_node(body.result_id, confidence=new_conf)
        await gs.flush()
        return _ok(node_id=body.result_id, confidence=new_conf, message="Feedback recorded")
    # 事件结果无置信度字段，反馈对事件不生效（保持兼容，不报错）
    return _ok(message="Feedback recorded (event results have no confidence field)")


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
        metadata=(
            node.metadata.model_dump()
            if hasattr(node.metadata, "model_dump")
            else dict(node.metadata)
        ),
        edges=[EdgeInfo(**e) for e in edges],
    )


@app.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """下发配置 — API Key 一律掩码（`xxx****xxxx`），绝不明文出网。"""
    return SettingsResponse(
        memory_db_path=settings.memory_db_path,
        graph_json_path=settings.graph_json_path,
        llm_base_url=settings.llm_base_url,
        llm_api_key=mask_secret(settings.llm_api_key),
        llm_model_name=settings.llm_model_name,
        llm_timeout=settings.llm_timeout,
        llm_max_tokens=settings.llm_max_tokens,
        llm_enable_thinking=settings.llm_enable_thinking,
        llm_thinking_budget=settings.llm_thinking_budget,
        available_providers=["primary", *settings.providers.keys()],
        providers={
            name: mask_provider_secret(entry)
            for name, entry in settings.providers.items()
        },
        active_provider=settings.active_provider,
        available_models=settings.available_models(),
        active_model=settings.active_model,
        agent_mode=settings.agent_mode,
        agent_max_retries=settings.agent_max_retries,
        agent_cr_model=settings.agent_cr_model,
        agent_in_model=settings.agent_in_model,
        agent_gr_model=settings.agent_gr_model,
        agent_meta_model=settings.agent_meta_model,
        max_graph_hops=settings.max_graph_hops,
        rrf_k=settings.rrf_k,
        jaccard_threshold=settings.jaccard_threshold,
        health_check_interval=settings.health_check_interval,
        health_check_timeout=settings.health_check_timeout,
        compensate_batch_size=settings.compensate_batch_size,
        log_level=settings.log_level,
    )


@app.put("/settings")
async def update_settings(body: SettingsUpdateRequest):
    data = body.model_dump(exclude_none=True)
    # 密钥幂等保留：掩码/空值 = 保留现值（前端把 GET 下发的掩码原样回传时不清钥）
    if "llm_api_key" in data:
        data["llm_api_key"] = resolve_secret(data["llm_api_key"], settings.llm_api_key)
    if "providers" in data:
        data["providers"] = {
            name: resolve_provider_secret(entry, settings.providers.get(name))
            for name, entry in data["providers"].items()
        }
    for field, value in data.items():
        if hasattr(settings, field):
            setattr(settings, field, value)
    settings.save_dpim_config()  # 持久化 BYOK/Agent 配置到 dpim.json，重启保留
    refresh_key()
    # 配置变更后立即健康检查一次：切换 provider/模型即刻生效，无需重启
    if compensator is not None:
        await compensator._check_llm()
    msg = "Settings updated and persisted to dpim.json; storage paths apply after restart"
    return _ok(message=msg)


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


@app.get("/agent/logs")
async def agent_logs(limit: int = 30, full: bool = False) -> dict[str, Any]:
    """返回最近 AI 调用日志（环形缓冲，新→旧），供前端观测 LLM 输入/输出。

    full=true 时返回完整 input/output/error（不做 2000 字符截断），供前端折叠查看。
    DPIM_AGENT_LOGS_FULL=false 时忽略 full 参数（日志含事件原文，部署环境可关闭全文防泄露）。
    """
    allow_full = full and settings.agent_logs_full
    return {"logs": get_llm_logs(limit=min(limit, 100), full=allow_full)}


@app.post("/agent/compensate")
async def agent_compensate() -> dict[str, Any]:
    """手动触发补偿：把 raw/indexed 事件重新入队走 Agent 管线（处理积压事件）。

    force=true：补偿退避暂停中也可强制执行并重置失败计数。
    """
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    await orchestrator.enqueue(
        QueueMessage(
            type="compensate",
            payload={"force": True},
            timestamp=datetime.now(timezone.utc).timestamp(),
        )
    )
    return _ok(message="Compensation triggered")


@app.post("/agent/maintain")
async def agent_maintain() -> dict[str, Any]:
    """手动触发图维护：扫描候选 → Gr 维护计划 → Meta 审核 → 执行。

    支持图结构调整/合并/删改（调整合并已有节点、删除僵尸节点、修正内容、删错误边）；
    写操作完成后刷新状态校验密钥（前端数据一致性）。
    """
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    await orchestrator.enqueue(
        QueueMessage(
            type="maintain_graph",
            payload={},
            timestamp=datetime.now(timezone.utc).timestamp(),
        )
    )
    refresh_key()
    return _ok(message="Graph maintenance triggered")
