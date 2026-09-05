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
from core.commands import parse_command, usage_text
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
    EventStatus,
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


app = FastAPI(title="DPIM", version="0.2.2", lifespan=lifespan)


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


def _command_response(message: str) -> IngestResponse:
    """指令响应：未创建事件，message 携带面向用户的执行结果。"""
    return IngestResponse(
        event_id="",
        status=EventStatus.skipped,
        message=message,
        command_triggered=True,
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest):
    es, gs = _stores()
    # 对话指令（^compress、^merge、^data 等）：确定层同步执行；语义层入队；
    # 均不落库为事件（存储类指令除外——它本身就是写事件）。
    cmd = parse_command(body.content)
    if cmd is not None:
        return await _dispatch_command(cmd)
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


async def _dispatch_command(cmd: Any) -> IngestResponse:
    es, gs = _stores()
    # ── ^help：只返回用法说明，不动数据 ──
    if cmd.kind == "help":
        return _command_response(usage_text())
    # ── 用法错误：只提示，不动数据 ──
    if cmd.hints:
        return _command_response(f"未执行：{cmd.hints[0]}")

    # ── 存储类：显式类型写事件（纯存储，AI 不可用也可用）──
    if cmd.kind == "store":
        eid, status = await es.insert_event(cmd.content, cmd.event_type)
        refresh_key()
        if settings.agent_mode == "pipeline" and ai_state.available and orchestrator:
            await orchestrator.enqueue(
                QueueMessage(
                    type="ingest",
                    payload={"event_id": eid},
                    timestamp=datetime.now(timezone.utc).timestamp(),
                )
            )
        logger.info("Command store type=%s event=%s", cmd.event_type, eid)
        return IngestResponse(
            event_id=eid,
            status=status,
            message=f"已按指令存入（{cmd.event_type}）",
        )

    # ── 压缩（语义层）：需 AI 可用 + 管线启用，否则明示拒绝 ──
    if cmd.kind == "compress":
        if settings.agent_mode != "pipeline" or not ai_state.available:
            return _command_response(
                "压缩指令未执行：AI 不可用或 Agent 管线未启用"
                "（^data 等纯存储指令不受影响）"
            )
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        if cmd.scope and gs.get_node(cmd.scope) is None:
            return _command_response(f"压缩指令未执行：限定节点不存在 {cmd.scope}")
        # 候选扫描前移到响应前（纯本地、毫秒级、无 LLM）：无候选立即明示
        # 「无需压缩」而非入队后静默空转——保守全图压缩的正确结果也要可感知
        from controller.tools.sys_tools import scan_maintenance_candidates

        candidates = scan_maintenance_candidates(gs)
        scope = cmd.scope
        if scope:
            candidates = {
                "merge_candidates": [
                    c for c in candidates["merge_candidates"]
                    if scope in (c["target_id"], c["source_id"])
                ],
                "zombie_nodes": [
                    c for c in candidates["zombie_nodes"] if c["node_id"] == scope
                ],
                "low_conf_isolated": [
                    c for c in candidates["low_conf_isolated"] if c["node_id"] == scope
                ],
                "compress_candidates": [
                    c for c in candidates["compress_candidates"] if c["node_id"] == scope
                ],
                "oversplit_events": [
                    c for c in candidates["oversplit_events"]
                    if scope in {n["node_id"] for n in c["nodes"]}
                ],
                "isolated_nodes": [
                    c for c in candidates["isolated_nodes"] if c["node_id"] == scope
                ],
                "link_candidates": [
                    c for c in candidates.get("link_candidates", [])
                    if scope in (c["node_a"], c["node_b"])
                ],
            }
        n_merge = len(candidates["merge_candidates"])
        n_zombie = len(candidates["zombie_nodes"])
        n_lowconf = len(candidates["low_conf_isolated"])
        n_compress = len(candidates["compress_candidates"])
        n_oversplit = len(candidates["oversplit_events"])
        n_isolated = len(candidates["isolated_nodes"])
        n_link = len(candidates.get("link_candidates", []))
        if not any([n_merge, n_zombie, n_lowconf, n_compress, n_oversplit, n_isolated, n_link]):
            scope_note = f"节点 {scope}" if scope else "全图"
            return _command_response(
                f"无需压缩：{scope_note}扫描未发现候选"
                "（无重合节点对 / 僵尸节点 / 冗长内容 / 过碎事件 / 待连线对）——已足够简练"
            )
        await orchestrator.enqueue(
            QueueMessage(
                type="maintain_graph",
                payload={"scope": scope} if scope else {},
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
        refresh_key()
        logger.info(
            "Command compress (scope=%s) -> maintain_graph "
            "(merge=%d zombie=%d lowconf=%d compress=%d oversplit=%d isolated=%d link=%d)",
            scope or "*", n_merge, n_zombie, n_lowconf, n_compress, n_oversplit,
            n_isolated, n_link,
        )
        scope_note = f"（限定节点 {scope}）" if scope else ""
        return _command_response(
            f"压缩指令已入队{scope_note}：发现候选（重合对 {n_merge} / "
            f"僵尸 {n_zombie} / 孤立低置信 {n_lowconf} / 冗长可压缩 {n_compress} / "
            f"同源过碎 {n_oversplit} / 孤立待连线 {n_isolated} / 待连线对 {n_link}），"
            "Gr 计划 → Meta 审核 → 执行稍后完成，结果见图页与日志"
        )

    # ── 优化（语义层，v1.24）：图结构优化两阶段——减碎+补缺 → 连线 ──
    if cmd.kind == "update":
        if settings.agent_mode != "pipeline" or not ai_state.available:
            return _command_response(
                "优化指令未执行：AI 不可用或 Agent 管线未启用"
                "（^data 等纯存储指令不受影响）"
            )
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        if cmd.scope and gs.get_node(cmd.scope) is None:
            return _command_response(f"优化指令未执行：限定节点不存在 {cmd.scope}")
        # 候选预扫描（update 口径：结构相关候选，与 compress 口径不同）
        from controller.tools.sys_tools import scan_maintenance_candidates

        candidates = scan_maintenance_candidates(gs)
        if cmd.scope:
            candidates = {
                "merge_candidates": [
                    c for c in candidates["merge_candidates"]
                    if cmd.scope in (c["target_id"], c["source_id"])
                ],
                "zombie_nodes": [
                    c for c in candidates["zombie_nodes"] if c["node_id"] == cmd.scope
                ],
                "low_conf_isolated": [
                    c for c in candidates["low_conf_isolated"] if c["node_id"] == cmd.scope
                ],
                "oversplit_events": [
                    c for c in candidates["oversplit_events"]
                    if cmd.scope in {n["node_id"] for n in c["nodes"]}
                ],
                "isolated_nodes": [
                    c for c in candidates["isolated_nodes"] if c["node_id"] == cmd.scope
                ],
                "link_candidates": [
                    c for c in candidates.get("link_candidates", [])
                    if cmd.scope in (c["node_a"], c["node_b"])
                ],
            }
        n_merge = len(candidates["merge_candidates"])
        n_zombie = len(candidates["zombie_nodes"])
        n_lowconf = len(candidates["low_conf_isolated"])
        n_oversplit = len(candidates["oversplit_events"])
        n_isolated = len(candidates["isolated_nodes"])
        n_link = len(candidates.get("link_candidates", []))
        if not any([n_merge, n_zombie, n_lowconf, n_oversplit, n_isolated, n_link]):
            scope_note = f"节点 {cmd.scope}" if cmd.scope else "全图"
            return _command_response(
                f"无需优化：{scope_note}扫描未发现结构优化候选"
                "（无冗余对 / 过碎事件 / 僵尸 / 孤立节点 / 待连线对）——图结构已良好"
            )
        await orchestrator.enqueue(
            QueueMessage(
                type="maintain_graph",
                payload={"mode": "update", "scope": cmd.scope} if cmd.scope
                else {"mode": "update"},
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
        refresh_key()
        logger.info(
            "Command update (scope=%s) -> maintain_graph update "
            "(merge=%d zombie=%d lowconf=%d oversplit=%d isolated=%d link=%d)",
            cmd.scope or "*", n_merge, n_zombie, n_lowconf, n_oversplit, n_isolated,
            n_link,
        )
        scope_note = f"（限定节点 {cmd.scope}）" if cmd.scope else ""
        return _command_response(
            f"优化指令已入队{scope_note}（两阶段）："
            f"减碎（重合对 {n_merge} / 同源过碎 {n_oversplit} / 僵尸 {n_zombie} / "
            f"低置信 {n_lowconf}，可补缺失要点）→ 连线（孤立待连 {n_isolated} / "
            f"待连线对 {n_link}）；执行稍后完成，结果见图页与日志"
        )

    # ── 指令消息（语义层，v1.27）：笼统自然语言意图 → Agent 管线 ──
    if cmd.kind == "cmdmsg":
        if settings.agent_mode != "pipeline" or not ai_state.available:
            return _command_response(
                "指令消息未执行：AI 不可用或 Agent 管线未启用"
                "（^data 等纯存储指令不受影响）"
            )
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        if len(cmd.content) > 2000:
            return _command_response(
                f"指令消息未执行：指令 {len(cmd.content)} 字符超过上限 2000"
                "（请精炼意图描述，具体数据交给管线自己查）"
            )
        # 预扫描（纯本地毫秒级）：无可动对象（无候选且无可挖掘事件）即时明示
        from controller.tools.sys_tools import scan_maintenance_candidates

        candidates = scan_maintenance_candidates(gs)
        n_merge = len(candidates["merge_candidates"])
        n_zombie = len(candidates["zombie_nodes"])
        n_lowconf = len(candidates["low_conf_isolated"])
        n_compress = len(candidates["compress_candidates"])
        n_oversplit = len(candidates["oversplit_events"])
        n_isolated = len(candidates["isolated_nodes"])
        n_link = len(candidates.get("link_candidates", []))
        n_mineable = len(await es.list_by_status("linked"))
        if not any([
            n_merge, n_zombie, n_lowconf, n_compress, n_oversplit,
            n_isolated, n_link, n_mineable,
        ]):
            return _command_response(
                "指令消息未执行：当前图无候选且无已构图事件，无可动对象"
            )
        await orchestrator.enqueue(
            QueueMessage(
                type="maintain_graph",
                payload={"instruction": cmd.content},
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
        refresh_key()
        logger.info(
            "Command cmdmsg -> maintain_graph (instruction=%r, merge=%d "
            "zombie=%d lowconf=%d compress=%d oversplit=%d isolated=%d "
            "link=%d mineable=%d)",
            cmd.content, n_merge, n_zombie, n_lowconf, n_compress,
            n_oversplit, n_isolated, n_link, n_mineable,
        )
        return _command_response(
            f"指令消息已入队：「{cmd.content}」——Gr 将读取指令在候选内决策"
            f"（重合对 {n_merge} / 僵尸 {n_zombie} / 孤立低置信 {n_lowconf} / "
            f"冗长可压缩 {n_compress} / 同源过碎 {n_oversplit} / 孤立待连线 "
            f"{n_isolated} / 待连线对 {n_link} / 可挖掘事件 {n_mineable}），"
            "Meta 审核后执行，多轮封顶，结果见图页与日志"
        )

    # ── 确定层：合并 / 删除 / 建系统节点（无 LLM，同步执行）──
    if cmd.kind == "merge":
        target = gs.get_node(cmd.target_id)
        source = gs.get_node(cmd.source_id)
        if target is None or source is None:
            missing = cmd.target_id if target is None else cmd.source_id
            return _command_response(f"合并未执行：节点不存在 {missing}")
        if target.node_id == source.node_id:
            return _command_response("合并未执行：目标与源是同一节点")
        if target.node_type != source.node_type:
            return _command_response(
                f"合并未执行：仅同类型可合并"
                f"（{target.title}={target.node_type.value}，"
                f"{source.title}={source.node_type.value}）"
            )
        if target.node_type.value == "system" or source.node_type.value == "system":
            return _command_response("合并未执行：system 节点禁止参与合并")
        removed = gs.merge_nodes(cmd.target_id, [cmd.source_id])
        if not removed:
            return _command_response("合并未执行：节点不存在或不可合并")
        await gs.upsert_node_fts(target.node_id, target.title, target.content)
        await gs.delete_node_fts(cmd.source_id)
        await gs.flush()
        refresh_key()
        logger.info("Command merge %s <- %s", cmd.target_id, removed)
        return _command_response(
            f"已合并 {removed[0]} → {cmd.target_id}"
            "（源证并集 + 内容合并，无丢失；源节点已删除）"
        )

    if cmd.kind == "delete":
        node = gs.get_node(cmd.node_id)
        if node is None:
            return _command_response(f"删除未执行：节点不存在 {cmd.node_id}")
        if node.node_type.value == "system":
            return _command_response(
                f"删除未执行：{node.title} 是 system 节点（手工创建、无事件来源，"
                "删除后不可恢复；如确需删除请用图页或 DELETE /nodes 接口）"
            )
        valid_refs = [sr for sr in node.source_refs if sr.valid]
        if valid_refs:
            return _command_response(
                f"删除未执行：{node.title} 有 {len(valid_refs)} 条有效源证，"
                "受删除保护（请在图页确认后处理）"
            )
        gs.remove_node(cmd.node_id)
        await gs.delete_node_fts(cmd.node_id)
        await gs.flush()
        refresh_key()
        logger.info("Command delete node %s", cmd.node_id)
        return _command_response(f"已删除节点 {cmd.node_id}（{node.title}）")

    if cmd.kind == "node":
        from core.models import GraphNode, NodeMetadata, NodeType

        if len(cmd.title) > 60:
            return _command_response(
                f"建节点未执行：标题 {len(cmd.title)} 字符超过上限 60"
                "（请精炼标题，正文放内容区）"
            )
        node_id = uuid.uuid4().hex[:16]
        node = GraphNode(
            node_id=node_id,
            title=cmd.title,
            content=cmd.content,
            node_type=NodeType.system,
            source_refs=[],
            confidence=0.7,
            metadata=NodeMetadata(evidence_quote=cmd.content, tags=[]),
        )
        gs.add_node(node)
        await gs.upsert_node_fts(node_id, node.title, node.content)
        await gs.flush()
        refresh_key()
        logger.info("Command node system created %s", node_id)
        return _command_response(f"系统节点已创建：{node_id}（{cmd.title}）")

    # 防御：未覆盖的指令类型
    return _command_response(f"未支持的指令类型：{cmd.kind}")


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
    has_content = bool(body.content.strip())
    has_source_op = bool(body.add_source_event_id or body.remove_source_event_id)
    if not has_content and not has_source_op:
        raise HTTPException(status_code=400, detail="No changes requested")
    # system 节点仅允许源事件管理（内容仍禁改——人工维护语义）
    if has_content and node.node_type.value == "system":
        raise HTTPException(status_code=403, detail="System nodes cannot be modified")
    if has_content:
        # update_node 统一标记脏位：修改必须落盘，杜绝静默丢失
        updated = gs.update_node(node_id, content=body.content, confidence=0.7)
        await gs.upsert_node_fts(node_id, updated.title, updated.content)
    if body.add_source_event_id:
        ev = await es.get(body.add_source_event_id)
        if ev is None:
            raise HTTPException(status_code=404, detail="Event not found")
        # 幂等追加：hash 与事件 content_hash 一致（「hash 供核对」不变式）
        gs.add_source_ref(node_id, body.add_source_event_id, ev["content_hash"])
    if body.remove_source_event_id:
        # 最少源证守卫：移除后必须仍保留 ≥1 条有效源证（溯源锚定不断线）
        remaining = [
            sr for sr in node.source_refs
            if sr.valid and sr.event_id != body.remove_source_event_id
        ]
        if not remaining:
            raise HTTPException(
                status_code=409,
                detail="Node must keep at least one valid source reference",
            )
        if not gs.remove_source_ref(node_id, body.remove_source_event_id):
            raise HTTPException(
                status_code=404,
                detail=f"Source reference {body.remove_source_event_id} not found on node",
            )
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
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    es, gs = _stores()
    if query and query.strip():
        # 关键词检索（v1.19）：直接走事件 FTS（含中文降级），再叠加 status/type 过滤与分页。
        # 供检索页「事件原文」模式使用——不再经由 /query 的 source_filter 过滤（那会滤成图节点而非事件）
        rows = await es.search_fts(query.strip(), limit=2000)
        filtered = [
            e for e in rows
            if (status is None or e["status"] == status)
            and (type is None or e["event_type"] == type)
        ]
        total = len(filtered)
        sliced = filtered[offset : offset + min(limit, 100)]
        items = [
            EventListItem(
                event_id=e["event_id"],
                created_at=e["created_at"],
                raw_content=e["raw_content"],
                event_type=e["event_type"],
                status=e["status"],
            )
            for e in sliced
        ]
        return EventListResponse(items=items, total=total, limit=limit, offset=offset)
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
    # 实时关联节点（v1.26）：行上的 graph_refs 是构图写入时的一次性快照，
    # 此后的合并/删除/聚合均不回写——图层反向索引才是当前权威。
    # 读路径实时派生（仅保留有效源证），前端「处理历史/图关联」随之变准。
    live_refs: list[str] = []
    for nid in gs.get_nodes_for_event(event_id):
        node = gs.get_node(nid)
        if node is None:
            continue
        if any(sr.event_id == event_id and sr.valid for sr in node.source_refs):
            live_refs.append(nid)
    event["graph_refs"] = live_refs
    return event


@app.get("/nodes", response_model=NodeListResponse)
async def list_nodes(
    type: str | None = None,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    es, gs = _stores()
    if query and query.strip():
        # 关键词检索（v1.19）：直接走节点 FTS（含中文降级），再叠加 type 过滤与分页。
        # 供检索页「知识节点」模式使用——不再经由 /query 的 source_filter 过滤
        rows = await gs.search_node_fts(query.strip(), limit=2000)
        filtered: list[dict[str, Any]] = []
        for row in rows:
            node = gs.get_node(row["node_id"])
            if node is None:
                continue
            if type is not None and node.node_type.value != type:
                continue
            filtered.append({
                "node_id": node.node_id,
                "title": node.title,
                "node_type": node.node_type.value,
                "confidence": node.confidence,
            })
        total = len(filtered)
        sliced = filtered[offset:offset + min(limit, 100)]
        return NodeListResponse(
            items=[NodeListItem(**n) for n in sliced],
            total=total, limit=limit, offset=offset,
        )
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
