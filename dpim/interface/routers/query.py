"""检索与联合列表 router：`/query`、`/feedback`、`/state-hash`。

联合列表 helper（`_joint_list_events` / `_joint_list_nodes`）也放这里：
`/events`（events.py）与 `/nodes`（nodes.py）复用它们，依赖方向单向（二者 → 本模块）。
"""

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from core.config import settings
from core.models import (
    EdgeListItem,
    EdgeListResponse,
    EventListItem,
    EventListResponse,
    FeedbackRequest,
    JointHitTrace,
    JointRepoTrace,
    JointTrace,
    NodeListItem,
    NodeListResponse,
    SearchRequest,
    SearchResponse,
    StateHashResponse,
)
from core.repos import (
    JOINT_CANDIDATE_FACTOR,
    JOINT_MIN_CANDIDATES,
    fuse_joint_results,
)
from core.search import search as hybrid_search
from core.state import ai_state, get_key
from interface import deps
from interface.deps import (
    _joint_repo_entries,
    _ok,
    _resolve_repo,
    _stores,
    logger,
)

router = APIRouter()


async def _joint_list_events(
    ids: list[str],
    *,
    status: str | None,
    event_type: str | None,
    query: str | None,
    limit: int,
    offset: int,
) -> EventListResponse:
    """联合事件列表（v1.30）：逐库取候选池 → 按 content_hash 去重 → 时间倒序 → 只切一次。

    修「检索页选『全部受管库』但事件原文模式静默退化为活动库」的缺口。
    """
    entries = _joint_repo_entries(ids)
    pool = min(max(limit * JOINT_CANDIDATE_FACTOR, JOINT_MIN_CANDIDATES), 100)
    merged: dict[str, EventListItem] = {}
    for entry in entries:
        es = entry.event_store
        if query and query.strip():
            rows = await es.search_fts(query.strip(), limit=2000)
            candidates = [
                row
                for row in rows
                if (status is None or row["status"] == status)
                and (event_type is None or row["event_type"] == event_type)
            ][:pool]
        else:
            candidates, _total = await es.list_events(
                status=status, event_type=event_type, limit=pool, offset=0
            )
        for row in candidates:
            key = str(row.get("content_hash") or row.get("event_id") or "")
            if not key or key in merged:
                continue
            # 来源库归属（v1.31）：首命中库写入 repo_id/repo_name（与 /query 融合口径一致）
            merged[key] = EventListItem(
                **{**row, "repo_id": entry.repo_id, "repo_name": entry.name}
            )
    ordered = sorted(merged.values(), key=lambda item: item.created_at, reverse=True)
    total = len(ordered)
    return EventListResponse(
        items=ordered[offset : offset + limit], total=total, limit=limit, offset=offset
    )


async def _joint_list_nodes(
    ids: list[str],
    *,
    node_type: str | None,
    query: str | None,
    limit: int,
    offset: int,
) -> NodeListResponse:
    """联合节点列表（v1.30）：逐库取候选池 → 按 (类型, 标题归一) 去重 → 只切一次。"""
    entries = _joint_repo_entries(ids)
    pool = min(max(limit * JOINT_CANDIDATE_FACTOR, JOINT_MIN_CANDIDATES), 100)
    merged: dict[tuple[str, str], NodeListItem] = {}
    for entry in entries:
        gs = entry.graph_store
        if query and query.strip():
            candidates: list[dict[str, Any]] = []
            for row in await gs.search_node_fts(query.strip(), limit=2000):
                node = gs.get_node(row["node_id"])
                if node is None:
                    continue
                if node_type is not None and node.node_type.value != node_type:
                    continue
                candidates.append(node.model_dump())
        else:
            candidates = gs.list_nodes(node_type=node_type)
        for data in candidates[:pool]:
            nid = str(data.get("node_id") or "")
            if not nid:
                continue
            # 枚举 → **值文本**：`str(NodeType.data)` 在 Python 3.11+ 是 `"NodeType.data"`
            # （不是 `"data"`），而单库路径经 Pydantic 落成 `"data"`——两条路必须同口径，
            # 否则前端「全部书目」下按类型筛选一个都匹配不上（链 AD 活体核实发现）。
            node_type_text = getattr(data.get("node_type"), "value", None) or str(
                data.get("node_type")
            )
            key = (
                str(node_type_text),
                str(data.get("title", "")).strip().casefold(),
            )
            if key in merged:
                continue
            merged[key] = NodeListItem(
                node_id=nid,
                title=str(data.get("title", "")),
                node_type=str(node_type_text),
                confidence=float(data.get("confidence") or 0.0),
                # 来源库归属（v1.31）：首命中库（去重后保留的负载）
                repo_id=entry.repo_id,
                repo_name=entry.name,
            )
    ordered = sorted(merged.values(), key=lambda item: (-item.confidence, item.node_id))
    total = len(ordered)
    return NodeListResponse(
        items=ordered[offset : offset + limit], total=total, limit=limit, offset=offset
    )


def _joint_list_edges(
    ids: list[str],
    *,
    node_id: str | None,
    source: str | None,
    target: str | None,
    relation: str | None,
    limit: int,
    offset: int,
) -> EdgeListResponse:
    """联合边列表（v1.37）：逐库取边 → 按 (source, target) 去重 → 稳定排序 → 只切一次。

    去重口径与 `_joint_list_nodes` 一致：同一份图层被复制/克隆成两个库时，只留首命中库
    的那条边（否则画布上会叠出两条完全重合的边）。单库内 (source, target) 天然唯一
    （NetworkX `Graph` 同端点只存一条边），故这里不做额外区分。
    """
    entries = _joint_repo_entries(ids)
    merged: dict[tuple[str, str], EdgeListItem] = {}
    for entry in entries:
        gs = entry.graph_store
        for row in gs.list_edges(
            node_id=node_id, source=source, target=target, relation=relation
        ):
            key = (str(row["source"]), str(row["target"]))
            if key in merged:
                continue
            merged[key] = EdgeListItem(
                source=key[0],
                target=key[1],
                relation=str(row["relation"]),
                evidence_event_id=str(row.get("evidence_event_id") or ""),
                # 来源库归属（v1.37）：首命中库（去重后保留的负载）
                repo_id=entry.repo_id,
                repo_name=entry.name,
            )
    # 稳定排序（(source, target) 全局唯一）→ 分页切分可复现
    ordered = sorted(merged.values(), key=lambda item: (item.source, item.target))
    total = len(ordered)
    return EdgeListResponse(
        items=ordered[offset : offset + limit], total=total, limit=limit, offset=offset
    )


@router.post("/query", response_model=SearchResponse)
async def query(body: SearchRequest):
    # 联合检索（v1.29）：显式多册，或未指定且存在多个受管库时，逐册检索后融合；
    # 单册（显式单册或仅默认库）走原有路径（管线可用时含 Agent 检索管线）
    use_joint = False
    if deps.repos is not None:
        if body.repo_ids is not None:
            use_joint = len(body.repo_ids) != 1
        else:
            use_joint = len(deps.repos.managed_entries()) > 1
    if use_joint:
        return await _joint_search(body)
    target = body.repo_ids[0] if body.repo_ids else None
    es, gs = _stores(target)
    resp: SearchResponse
    if settings.agent_mode == "pipeline" and ai_state.available and deps.orchestrator:
        try:
            resp = await deps.orchestrator.run_query(body, es, gs)
        except Exception:
            logger.exception("Query agent pipeline failed, fallback to hybrid search")
            resp = await hybrid_search(body, es, gs, degraded=not ai_state.available)
    else:
        resp = await hybrid_search(body, es, gs, degraded=not ai_state.available)
    # 来源册锚定（v1.29）：单册结果同样携带所属册
    entry = _resolve_repo(target)
    if entry is not None:
        for r in resp.results:
            r.repo_id, r.repo_name = entry.repo_id, entry.name
    return resp


async def _joint_search(body: SearchRequest) -> SearchResponse:
    """库间联合检索：逐库候选池 → 等权 RRF 融合 + 去重 + 来源锚定（纯本地，降级可用）。

    v1.30 修正：**每库取候选池**（`limit × 系数`，下限 50），融合后**只切一次**分页。
    原实现把 `limit/offset` 原样传给每库、融合后又切一次 → 双重分页：
    第二页是在「各库各自第二页」的融合结果上再切片，结果错乱；`total` 也只反映候选数。
    """
    if body.repo_ids is None:
        entries = deps.repos.managed_entries()  # 缺省 = 全部受管库
    else:
        entries = []
        for bid in body.repo_ids:
            record = deps.repos.records.get(bid)
            if record is None or not record.managed or bid not in deps.repos.entries:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown or unmanaged repo: {bid}",
                )
            entries.append(deps.repos.entries[bid])
    degraded = not ai_state.available
    pool = min(max(body.limit * JOINT_CANDIDATE_FACTOR, JOINT_MIN_CANDIDATES), 100)
    probe = body.model_copy(update={"limit": pool, "offset": 0})
    started = time.perf_counter()

    per_repo: list[tuple[Any, SearchResponse]] = []
    repo_traces: list[JointRepoTrace] = []
    for entry in entries:
        repo_started = time.perf_counter()
        resp = await hybrid_search(
            probe, entry.event_store, entry.graph_store, degraded=degraded
        )
        per_repo.append((entry, resp))
        repo_traces.append(
            JointRepoTrace(
                repo_id=entry.repo_id,
                repo_name=entry.name,
                candidates=len(resp.results),
                elapsed_ms=int((time.perf_counter() - repo_started) * 1000),
            )
        )

    fused, stats = fuse_joint_results(per_repo)
    order = sorted(
        range(len(fused)),
        key=lambda i: (-fused[i].score, fused[i].repo_id, fused[i].node_id),
    )
    total = len(order)
    page_indices = order[body.offset : body.offset + body.limit]
    paged = [fused[i] for i in page_indices]
    trace = JointTrace(
        candidate_pool=pool,
        merged_total=stats["merged_total"],
        deduped=stats["deduped"],
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        per_repo=repo_traces,
        hits=[
            JointHitTrace(
                node_id=hit.node_id,
                title=hit.title,
                kind=hit.kind,
                repo_id=hit.repo_id,
                repo_name=hit.repo_name,
                source_repos=hit.source_repos,
                contributions=stats["contribs"][index],
            )
            for index, hit in zip(page_indices, paged)
        ],
    )
    return SearchResponse(results=paged, total=total, degraded=degraded, trace=trace)


@router.post("/feedback")
async def feedback(body: FeedbackRequest):
    # 库作用域（v1.30）：跨库结果反馈此前静默落在活动库上（改了别的库或什么都不改）
    es, gs = _stores(body.repo_id or None)
    # result_id is a node_id or event_id
    node = gs.get_node(body.result_id)
    if node:
        if node.node_type.value in ("system", "data"):
            return _ok(message="System/data nodes not affected by feedback")
        delta = 0.01 if body.accepted else -0.02
        new_conf = max(0.1, min(1.0, node.confidence + delta))
        # 脏位由写请求收口（write_commit 中间件）统一落盘，此处不再单独 flush
        gs.update_node(body.result_id, confidence=new_conf)
        return _ok(node_id=body.result_id, confidence=new_conf, message="Feedback recorded")
    # 事件结果无置信度字段，反馈对事件不生效（保持兼容，不报错）
    return _ok(message="Feedback recorded (event results have no confidence field)")


# ── dpim-webui 新增端点 ────────────────────

@router.get("/state-hash", response_model=StateHashResponse)
async def state_hash():
    es, gs = _stores()
    changed_at = await es.last_event_at()
    return StateHashResponse(hash=get_key(), changed_at=changed_at or "")
