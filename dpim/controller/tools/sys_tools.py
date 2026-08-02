"""Sys 纯函数工具 — 直接复用存储层/检索层，不做任何 LLM 调用。

所有工具接收存储实例为参数，保持无状态、可测试。
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from core.config import settings
from core.models import (
    GraphEdge,
    GraphNode,
    MetaCogIssue,
    MetaCogVerdict,
    NodeMetadata,
    NodeType,
    SearchRequest,
    SearchResponse,
    SourceRef,
)


async def tool_graph_query(graph_store: Any, query_text: str, limit: int = 10) -> list[GraphNode]:
    """图谱近似节点查询：按文本在节点 FTS 中检索相似已有节点。"""
    rows = await graph_store.search_node_fts(query_text, limit=limit)
    nodes: list[GraphNode] = []
    for r in rows:
        node = graph_store.get_node(r["node_id"])
        if node is not None:
            nodes.append(node)
    return nodes


async def tool_graph_expand(
    graph_store: Any, seed_nodes: list[str], hops: int = 2
) -> dict[str, float]:
    """图 k 跳扩散：返回 {node_id: 得分}。"""
    return cast(dict[str, float], graph_store.ego_graph(seed_nodes, hops=hops))


async def tool_direct_search(
    event_store: Any, graph_store: Any, request: SearchRequest
) -> SearchResponse:
    """直接全文检索（FTS5 降级路径），返回 SearchResponse。"""
    from core.search import search as hybrid_search

    return await hybrid_search(request, event_store, graph_store, degraded=True)


def tool_rrf_merge(
    c1: dict[str, float], c2: dict[str, float], k: int | None = None
) -> list[tuple[str, float]]:
    """RRF 融合两个得分字典，返回按最终得分降序的 (key, score) 列表。"""
    k = k or settings.rrf_k
    keys = set(c1) | set(c2)
    s1 = sorted(c1.keys(), key=lambda x: c1[x], reverse=True)
    s2 = sorted(c2.keys(), key=lambda x: c2[x], reverse=True)
    max_rank = max(len(s1), len(s2)) + 1
    scores: dict[str, float] = {}
    for key in keys:
        r1 = s1.index(key) + 1 if key in c1 else max_rank
        r2 = s2.index(key) + 1 if key in c2 else max_rank
        scores[key] = (1.0 / (k + r1)) + (1.0 / (k + r2))
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


async def tool_apply_to_store(
    event_store: Any, graph_store: Any, proposal: Any, event_id: str
) -> list[str]:
    """将审核通过的图构建计划写入存储层（幂等：节点/边已存在则复用）。"""
    event = await event_store.get(event_id)
    c_hash = event["content_hash"] if event else ""

    created: list[str] = []
    id_by_title: dict[str, str] = {}

    # merged_into：追加内容到已有节点
    merged = graph_store.get_node(proposal.merged_into) if proposal.merged_into else None
    if merged is not None:
        lines = [nc.content for nc in proposal.new_nodes if nc.content]
        if lines:
            merged.content = (merged.content + "\n" + "\n".join(lines)).strip()
            graph_store.graph.nodes[merged.node_id]["data"] = merged
            await graph_store.upsert_node_fts(merged.node_id, merged.title, merged.content)
        created.append(merged.node_id)

    # 新建节点
    for nc in proposal.new_nodes:
        nid = uuid.uuid4().hex[:16]
        node = GraphNode(
            node_id=nid,
            title=nc.title,
            content=nc.content,
            node_type=NodeType(nc.node_type),
            source_refs=[SourceRef(event_id=event_id, valid=True, hash=c_hash)],
            confidence=nc.confidence,
            metadata=NodeMetadata(evidence_quote=nc.evidence_quote, tags=[]),
        )
        graph_store.add_node(node)
        await graph_store.upsert_node_fts(nid, nc.title, nc.content)
        id_by_title[nc.title] = nid
        created.append(nid)

    # 新建边（source/target 支持新节点 title 或已有 node_id）
    for ec in proposal.new_edges:
        src = id_by_title.get(ec.source, ec.source)
        tgt = id_by_title.get(ec.target, ec.target)
        if graph_store.get_node(src) is not None and graph_store.get_node(tgt) is not None:
            graph_store.add_edge(
                GraphEdge(
                    source=src,
                    target=tgt,
                    relation=ec.relation,
                    evidence_event_id=ec.evidence_event_id or event_id,
                )
            )

    await graph_store.flush()
    await event_store.update_status(event_id, "linked", graph_refs=created)
    return created


# ── Meta 本地检查（无 LLM）──

def run_local_checks(
    graph_store: Any, proposal: Any, source_content: str
) -> list[MetaCogIssue]:
    """来源锚定 / 边合法性 / 空节点 的本地逻辑检查。

    纯确定性检查，不调 LLM。有任一问题即返回 fail 级 issues。
    """
    issues: list[MetaCogIssue] = []
    new_titles = {nc.title for nc in proposal.new_nodes}

    for nc in proposal.new_nodes:
        if not (nc.content or "").strip():
            issues.append(
                MetaCogIssue(
                    type="empty_node",
                    description=f"节点内容为空：{nc.title}",
                    suggestion="补充原文摘要",
                )
            )
        quote = (nc.evidence_quote or "").strip()
        if quote and quote not in source_content:
            issues.append(
                MetaCogIssue(
                    type="hallucination",
                    description=f"evidence_quote 未在原文中找到：{nc.title}",
                    suggestion="改为原文连续子串摘录",
                )
            )

    for ec in proposal.new_edges:
        if ec.source not in new_titles and graph_store.get_node(ec.source) is None:
            issues.append(
                MetaCogIssue(
                    type="illegal_edge",
                    description=f"边 source 节点不存在：{ec.source}",
                    suggestion="使用已有节点 id 或本计划新节点 title",
                )
            )
        if ec.target not in new_titles and graph_store.get_node(ec.target) is None:
            issues.append(
                MetaCogIssue(
                    type="illegal_edge",
                    description=f"边 target 节点不存在：{ec.target}",
                    suggestion="使用已有节点 id 或本计划新节点 title",
                )
            )
    return issues


def empty_verdict(issues: list[MetaCogIssue]) -> MetaCogVerdict:
    return MetaCogVerdict(verdict="fail", issues=issues)
