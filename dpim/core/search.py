"""FTS5 关键词召回 → 图扩散 → RRF 融合排序"""

import json
from datetime import datetime, timezone

from core.config import settings
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import SearchRequest, SearchResponse, SearchResult


def _time_decay(event_type: str, days: float) -> float:
    if event_type == "interaction":
        return 1.0 / (1.0 + days * 0.05)
    return 1.0


def retain_relevant_expansion(
    graph_store: GraphStore, keys: dict[str, float], query: str
) -> dict[str, float]:
    """图扩散召回相关性过滤：仅保留 title/content 与查询切词有重叠的节点。

    无向扩散会把「与种子相连但与查询无关」的节点（如搜「游戏」带出「八段锦」）
    混入召回。此过滤把扩散结果限定在与查询有词面重叠的节点上，
    显著降低无关噪声（用户诉求：尽量无关的不做）。
    """
    from core.text_utils import tokenize_query

    tokens = [t for t in tokenize_query(query) if len(t) >= 2]
    if not tokens:
        return keys
    out: dict[str, float] = {}
    for k, v in keys.items():
        node = graph_store.get_node(k)
        if node is None:
            continue
        text = f"{node.title or ''} {node.content or ''}".lower()
        if any(t.lower() in text for t in tokens):
            out[k] = v
    return out


async def search(
    request: SearchRequest,
    event_store: EventStore,
    graph_store: GraphStore,
    degraded: bool = False,
) -> SearchResponse:
    now = datetime.now(timezone.utc)

    if not request.query.strip():
        return SearchResponse(results=[], total=0, degraded=degraded)

    # Step 1: FTS5 keyword recall
    event_rows = await event_store.search_fts(request.query, limit=100)
    node_rows = await graph_store.search_node_fts(request.query, limit=100)

    c1: dict[str, float] = {}
    event_node_map: dict[str, list[str]] = {}

    for r in event_rows:
        eid = r["event_id"]
        gr = json.loads(r.get("graph_refs", "[]"))
        score = -r["rank"]
        event_node_map[eid] = gr
        if gr:
            for nid in gr:
                if nid not in c1 or score > c1[nid]:
                    c1[nid] = score
        else:
            if eid not in c1 or score > c1[eid]:
                c1[eid] = score

    for r in node_rows:
        nid = r["node_id"]
        score = -r["rank"]
        if nid not in c1 or score > c1[nid]:
            c1[nid] = score

    # Apply source_filter
    if request.source_filter != "all":
        filtered = {}
        events = await event_store.get_many([k for k in c1 if k in event_node_map])
        for key in c1:
            node = graph_store.get_node(key)
            if node is not None and node.node_type.value == request.source_filter:
                filtered[key] = c1[key]
            elif key in event_node_map:
                ev = events.get(key)
                if ev and ev["event_type"] == request.source_filter:
                    filtered[key] = c1[key]
        c1 = filtered

    if degraded:
        results = await _build_results(c1, event_store, graph_store, event_node_map)
        sorted_results = sorted(results, key=lambda x: x.score, reverse=True)
        total = len(sorted_results)
        paged = sorted_results[request.offset : request.offset + request.limit]
        return SearchResponse(results=paged, total=total, degraded=True)

    # Step 2: Graph diffusion（扩散召回做相关性过滤：无向扩散会把与查询无关的邻居
    # 如搜「游戏」带出「八段锦」混入结果，按查询词重叠过滤掉）
    seeds = [k for k in c1 if graph_store.get_node(k) is not None]
    c2 = retain_relevant_expansion(
        graph_store, graph_store.ego_graph(seeds, hops=request.max_hops), request.query
    )

    # Step 3: RRF fusion（两路：FTS5 + 图扩散）
    k = settings.rrf_k
    sorted_c1 = sorted(c1.keys(), key=lambda x: c1[x], reverse=True)
    sorted_c2 = sorted(c2.keys(), key=lambda x: c2[x], reverse=True)
    max_rank = max(len(sorted_c1), len(sorted_c2)) + 1
    # 预构建 rank 字典：O(1) 查找，避免每次 .index() 的 O(n) 遍历
    rank1_map = {key: i + 1 for i, key in enumerate(sorted_c1)}
    rank2_map = {key: i + 1 for i, key in enumerate(sorted_c2)}

    rrf_scores: dict[str, float] = {}
    all_keys = set(c1.keys()) | set(c2.keys())

    for key in all_keys:
        rank1 = rank1_map.get(key, max_rank)
        rank2 = rank2_map.get(key, max_rank)
        rrf_scores[key] = (
            (1.0 / (k + rank1)) + (1.0 / (k + rank2))
        )

    # Apply time decay
    first_ref_ids: list[str] = []
    for key in rrf_scores:
        node = graph_store.get_node(key)
        if node is not None and node.source_refs:
            first_ref_ids.append(node.source_refs[0].event_id)
    first_ref_events = await event_store.get_many(first_ref_ids)
    for key in rrf_scores:
        source_type = "interaction"
        node = graph_store.get_node(key)
        if node:
            source_type = node.node_type.value
        days_since = 0.0
        refs = node.source_refs if node else []
        if refs:
            ev = first_ref_events.get(refs[0].event_id)
            if ev:
                created = datetime.fromisoformat(ev["created_at"])
                days_since = (now - created).total_seconds() / 86400.0
        rrf_scores[key] *= _time_decay(source_type, days_since)

    results = await _build_results(rrf_scores, event_store, graph_store, event_node_map)
    sorted_results = sorted(results, key=lambda x: x.score, reverse=True)
    total = len(sorted_results)
    paged = sorted_results[request.offset : request.offset + request.limit]
    return SearchResponse(results=paged, total=total, degraded=False)


async def _build_results(
    scores: dict[str, float],
    event_store: EventStore,
    graph_store: GraphStore,
    event_node_map: dict[str, list[str]],
) -> list[SearchResult]:
    results: list[SearchResult] = []
    events = await event_store.get_many(
        [key for key in scores if graph_store.get_node(key) is None]
    )
    for key, score in scores.items():
        node = graph_store.get_node(key)
        if node:
            title = node.title
            snippet = node.content[:200]
            source_events = [sr.event_id for sr in node.source_refs if sr.valid]
            source_type = node.node_type.value
            conf = node.confidence
            results.append(SearchResult(
                node_id=key,
                title=title,
                snippet=snippet,
                score=score,
                source_events=source_events,
                source_type=source_type,
                confidence=conf,
                degraded=False,
            ))
        else:
            # 非图节点 key：可能是无图节点关联的事件（含 orchestrator 以空
            # map 调用的场景），回退查事件表；查不到则跳过
            ev = events.get(key)
            if ev:
                results.append(SearchResult(
                    node_id=key,
                    title=ev["event_id"],
                    snippet=ev["raw_content"][:200],
                    score=score,
                    source_events=[ev["event_id"]],
                    source_type=ev["event_type"],
                    confidence=0.5,
                    degraded=False,
                ))
    return results
