"""事件线 router：`POST /ingest`（含 `^指令` 分发）、`/events*`。

`_dispatch_command` 也在这里：它是 `/ingest` 的指令分支实现，与存储类指令同源。
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from core.commands import parse_command, usage_text
from core.config import settings
from core.models import (
    EventListItem,
    EventListResponse,
    IngestRequest,
    IngestResponse,
    ModifyEventRequest,
    ModifyEventStatusRequest,
    QueueMessage,
)
from core.state import ai_state
from interface import deps
from interface.deps import (
    ALLOWED_EVENT_TRANSITIONS,
    _command_response,
    _ok,
    _parse_repo_ids,
    _resolve_repo,
    _stores,
    logger,
)
from interface.routers.query import _joint_list_events

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest):
    es, gs = _stores(body.repo_id or None)
    entry = _resolve_repo(body.repo_id or None)
    repo_id = entry.repo_id if entry else ""
    # 对话指令（^compress、^merge、^data 等）：确定层同步执行；语义层入队；
    # 均不落库为事件（存储类指令除外——它本身就是写事件）。
    cmd = parse_command(body.content)
    if cmd is not None:
        return await _dispatch_command(cmd, body.repo_id or None)
    eid, status = await es.insert_event(body.content, body.event_type.value)
    # Agent 管线启用时，入队让管线即时处理（异步，不阻塞写入返回）
    if settings.agent_mode == "pipeline" and ai_state.available and deps.orchestrator:
        ingest_payload = {"event_id": eid}
        if repo_id:
            ingest_payload["repo_id"] = repo_id
        await deps.orchestrator.enqueue(
            QueueMessage(
                type="ingest",
                payload=ingest_payload,
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
    return IngestResponse(event_id=eid, status=status, message="Event ingested")


async def _dispatch_command(cmd: Any, scope: str | None = None) -> IngestResponse:
    # 指令作用域 = 指定库（缺省 = 活动库）。v1.30 修正：此前固定取活动库，
    # 传了 repo_id 的指令会静默落到活动库上。
    es, gs = _stores(scope)
    entry = _resolve_repo(scope)
    repo_id = entry.repo_id if entry else ""

    def _payload(extra: dict) -> dict:
        return {"repo_id": repo_id, **extra} if repo_id else extra

    # ── ^help：只返回用法说明，不动数据 ──
    if cmd.kind == "help":
        return _command_response(usage_text())
    # ── 用法错误：只提示，不动数据 ──
    if cmd.hints:
        return _command_response(f"未执行：{cmd.hints[0]}")

    # ── 存储类：显式类型写事件（纯存储，AI 不可用也可用）──
    if cmd.kind == "store":
        eid, status = await es.insert_event(cmd.content, cmd.event_type)
        if settings.agent_mode == "pipeline" and ai_state.available and deps.orchestrator:
            await deps.orchestrator.enqueue(
                QueueMessage(
                    type="ingest",
                    payload=_payload({"event_id": eid}),
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
        if deps.orchestrator is None:
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
        await deps.orchestrator.enqueue(
            QueueMessage(
                type="maintain_graph",
                payload=_payload({"scope": scope} if scope else {}),
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
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
        if deps.orchestrator is None:
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
        await deps.orchestrator.enqueue(
            QueueMessage(
                type="maintain_graph",
                payload=_payload({"mode": "update", "scope": cmd.scope} if cmd.scope
                                 else {"mode": "update"}),
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
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
        if deps.orchestrator is None:
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
        await deps.orchestrator.enqueue(
            QueueMessage(
                type="maintain_graph",
                payload=_payload({"instruction": cmd.content}),
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
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
        logger.info("Command node system created %s", node_id)
        return _command_response(f"系统节点已创建：{node_id}（{cmd.title}）")

    # 防御：未覆盖的指令类型
    return _command_response(f"未支持的指令类型：{cmd.kind}")


@router.delete("/events/{event_id}")
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


@router.put("/events/{event_id}/status")
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
        and deps.orchestrator
    ):
        entry = _resolve_repo()
        retry_payload = {"event_id": event_id}
        if entry:
            retry_payload["repo_id"] = entry.repo_id
        await deps.orchestrator.enqueue(
            QueueMessage(
                type="ingest",
                payload=retry_payload,
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
        )
    return _ok(event_id=event_id, new_status=new, message="Status updated")


@router.put("/events/{event_id}")
async def modify_event(event_id: str, body: ModifyEventRequest):
    es, gs = _stores()
    ok = await es.update_content(event_id, body.content, gs)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found")
    # 可选类型修订：仅改线层，不联动已生成图节点
    if body.event_type is not None:
        await es.update_type(event_id, body.event_type.value)
    return _ok(event_id=event_id, message="Event content updated")


@router.get("/events", response_model=EventListResponse)
async def list_events(
    status: str | None = None,
    type: str | None = None,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
    repo_id: str | None = None,
    repo_ids: str | None = None,
):
    scope = _parse_repo_ids(repo_ids)
    if scope:
        return await _joint_list_events(
            scope, status=status, event_type=type, query=query, limit=limit, offset=offset
        )
    es, gs = _stores(repo_id)
    # 来源库归属（v1.31）：单库查询也填该库 id/name（库登记未初始化时为空串）
    entry = _resolve_repo(repo_id)
    owner_id = entry.repo_id if entry else ""
    owner_name = entry.name if entry else ""
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
                error=e.get("error", ""),
                repo_id=owner_id,
                repo_name=owner_name,
            )
            for e in sliced
        ]
        return EventListResponse(items=items, total=total, limit=limit, offset=offset)
    items, total = await es.list_events(
        status=status, event_type=type, limit=min(limit, 100), offset=offset,
    )
    return EventListResponse(
        items=[
            EventListItem(**{**e, "repo_id": owner_id, "repo_name": owner_name})
            for e in items
        ],
        total=total, limit=limit, offset=offset,
    )


@router.get("/events/{event_id}")
async def get_event(event_id: str, repo_id: str | None = None):
    # 库作用域（v1.30）：跨库跳转来的事件详情此前只在活动库里找 → 静默 404
    es, gs = _stores(repo_id)
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
