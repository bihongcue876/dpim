"""图层 router：`/nodes*`、`/edges`、`/graph`。"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from core.models import (
    CreateEdgeRequest,
    CreateNodeRequest,
    DeleteNodeRequest,
    EdgeInfo,
    EdgeListItem,
    EdgeListResponse,
    GraphEdge,
    ModifyNodeRequest,
    NodeDetailResponse,
    NodeListItem,
    NodeListResponse,
)
from core.trash import archive_graph, archive_node
from interface.deps import (
    _database,
    _ok,
    _parse_repo_ids,
    _resolve_repo,
    _stores,
    logger,
)
from interface.routers.query import _joint_list_edges, _joint_list_nodes

router = APIRouter()

# 边列表 limit 值域（v1.37）：越界显式 400，不静默截断（与 GET /logs 的 tail 同一风格）。
# 上限 5000 是「图谱页一次取全」的余量：节点上限 400 时边通常 <1000。
_EDGE_LIMIT_MIN, _EDGE_LIMIT_MAX = 0, 5000


@router.delete("/nodes/{node_id}")
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
    # 删除前留档到回收站：节点本体 + 关联边（v1.31，供恢复端点尽力补回边）
    archive_node(gs.json_path, node.model_dump(), gs.list_edges(node_id=node_id))
    gs.remove_node(node_id)
    await gs.delete_node_fts(node_id)
    if gs.dirty:
        await gs.save()
    return _ok(message="Node deleted")


@router.put("/nodes/{node_id}")
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
    return _ok(node_id=node_id, message="Node updated")


@router.post("/edges")
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
    return _ok(message="Edge created")


@router.delete("/edges")
async def delete_edge(source: str, target: str):
    es, gs = _stores()
    ok = gs.remove_edge(source, target)
    if not ok:
        raise HTTPException(status_code=404, detail="Edge not found")
    return _ok(message="Edge deleted")


@router.get("/edges", response_model=EdgeListResponse)
async def list_edges(
    source: str | None = None,
    target: str | None = None,
    node_id: str | None = None,
    relation: str | None = None,
    limit: int = 200,
    offset: int = 0,
    repo_id: str | None = None,
    repo_ids: str | None = None,
):
    """边列表（v1.37）：图谱页一次取全，替代「逐节点取详情再汇总边」。

    筛选：`node_id`（**两侧**命中，出边 + 入边）/ `source` / `target` / `relation`。
    作用域：`repo_id`（缺省活动库）或 `repo_ids=a,b`（联合：按 (source, target) 去重 +
    首命中库归属）。排序：(source, target) 稳定序，故分页可复现。
    """
    if not (_EDGE_LIMIT_MIN <= limit <= _EDGE_LIMIT_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"limit 须在 {_EDGE_LIMIT_MIN}..{_EDGE_LIMIT_MAX} 之间（收到 {limit}）",
        )
    if offset < 0:
        raise HTTPException(status_code=400, detail=f"offset 不能为负（收到 {offset}）")
    scope = _parse_repo_ids(repo_ids)
    if scope:
        return _joint_list_edges(
            scope,
            node_id=node_id,
            source=source,
            target=target,
            relation=relation,
            limit=limit,
            offset=offset,
        )
    es, gs = _stores(repo_id)
    # 来源库归属（v1.37）：单库查询也填该库 id/name（库登记未初始化时为空串）
    entry = _resolve_repo(repo_id)
    owner_id = entry.repo_id if entry else ""
    owner_name = entry.name if entry else ""
    rows = gs.list_edges(node_id=node_id, source=source, target=target, relation=relation)
    rows.sort(key=lambda e: (e["source"], e["target"]))
    return EdgeListResponse(
        items=[
            EdgeListItem(**{**row, "repo_id": owner_id, "repo_name": owner_name})
            for row in rows[offset : offset + limit]
        ],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.post("/nodes")
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
    return _ok(node_id=node_id, message="Node created")


@router.delete("/graph")
async def clear_graph():
    """清空活动书目的图层（v1.42）：**先留档整图 → 撤销线层派生链接 → 再清空**。

    顺序不能颠倒：留档必须发生在清空之前；撤销派生链接必须与清空同一次请求内完成，
    否则线层会一直声称「已入图 N」（graph_refs 指向已不存在的节点，且 linked 不在
    补偿队列里 → 图再也长不回来）。留档失败仍照常清空，但响应里明说「不可恢复」。
    """
    es, gs = _stores()
    db = _database()
    nodes = gs.list_nodes()
    edges = gs.list_edges()
    archive_path = archive_graph(db.db_path, nodes, edges)
    unlink = await es.unlink_graph_refs()
    gs.clear_all()
    # 清空 node_fts：避免旧节点留在全文索引导致检索召回残留
    await gs.rebuild_node_fts()
    archive_id = archive_path.stem if archive_path else ""
    logger.warning(
        "图层清空：%d 节点 / %d 边（留档 %s）；撤销派生链接 %d 条 / 回退 indexed %d 条",
        len(nodes), len(edges), archive_id or "失败",
        unlink["cleared"], unlink["relinked"],
    )
    message = f"图层已清空（{len(nodes)} 节点 / {len(edges)} 边）"
    message += (
        f"；已留档 {archive_id}（回收站可恢复）" if archive_path
        else "；留档失败，此操作不可恢复"
    )
    if unlink["relinked"]:
        message += f"；{unlink['relinked']} 条事件回到「待处理」（可重新入图）"
    return _ok(
        message=message,
        archived=bool(archive_path),
        archive_id=archive_id,
        cleared_nodes=len(nodes),
        cleared_edges=len(edges),
        unlinked_events=unlink["cleared"],
        relinked_events=unlink["relinked"],
    )


@router.get("/nodes", response_model=NodeListResponse)
async def list_nodes(
    type: str | None = None,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
    repo_id: str | None = None,
    repo_ids: str | None = None,
):
    scope = _parse_repo_ids(repo_ids)
    if scope:
        return await _joint_list_nodes(
            scope, node_type=type, query=query, limit=limit, offset=offset
        )
    es, gs = _stores(repo_id)
    # 来源库归属（v1.31）：单库查询也填该库 id/name（库登记未初始化时为空串）
    entry = _resolve_repo(repo_id)
    owner_id = entry.repo_id if entry else ""
    owner_name = entry.name if entry else ""
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
                "repo_id": owner_id,
                "repo_name": owner_name,
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
        items=[
            NodeListItem(**{**n, "repo_id": owner_id, "repo_name": owner_name})
            for n in sliced
        ],
        total=total, limit=limit, offset=offset,
    )


@router.get("/nodes/{node_id}", response_model=NodeDetailResponse)
async def get_node(node_id: str, repo_id: str | None = None):
    es, gs = _stores(repo_id)
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
