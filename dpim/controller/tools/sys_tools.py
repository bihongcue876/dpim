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


async def tool_graph_query(graph_store: Any, query_text: str, limit: int = 15) -> list[GraphNode]:
    """图谱近似节点查询：FTS5/多词 LIKE 召回 + 词重叠补充。

    单纯 FTS 在中文/弱模型下召回差，Gr 看不到「沾边」节点 → 容易建冗余节点。
    这里在 FTS 结果之外，补充与查询词重叠较高的节点（确定性、无 LLM）。
    """
    rows = await graph_store.search_node_fts(query_text, limit=limit)
    nodes: list[GraphNode] = []
    seen: set[str] = set()
    for r in rows:
        node = graph_store.get_node(r["node_id"])
        if node is not None:
            nodes.append(node)
            seen.add(node.node_id)

    # 词重叠补充召回：查询词与节点词重叠 ≥ 阈值的未命中节点补入（limit 内）
    from core.text_utils import tokenize_query

    q_tokens = set(tokenize_query(query_text))
    if q_tokens and len(nodes) < limit:
        need = max(2, int(len(q_tokens) * 0.3))
        for nid, ndata in graph_store.graph.nodes(data="data"):
            if ndata is None or nid in seen or len(nodes) >= limit:
                continue
            nt = set(tokenize_query(f"{ndata.title} {ndata.content}"))
            if not nt:
                continue
            if len(q_tokens & nt) >= need:
                nodes.append(ndata)
                seen.add(nid)
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
    # 预构建 rank 字典：O(1) 查找
    r1_map = {key: i + 1 for i, key in enumerate(s1)}
    r2_map = {key: i + 1 for i, key in enumerate(s2)}
    scores: dict[str, float] = {}
    for key in keys:
        r1 = r1_map.get(key, max_rank)
        r2 = r2_map.get(key, max_rank)
        scores[key] = (1.0 / (k + r1)) + (1.0 / (k + r2))
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def find_redundant_node(
    graph_store: Any, new_node: Any, candidates: list[Any]
) -> str | None:
    """系统去重预检：新节点与候选节点词重叠 Jaccard ≥ 阈值且同类型 → 返回目标 node_id。

    确定性、无 LLM；阈值取 JACCARD_THRESHOLD（默认 0.85，保守防误伤）。
    只有「近乎同一观点」才自动改道合并，其余保留新建（由 Gr/Meta 语义判断）。
    """
    from core.text_utils import tokenize_query

    tokens = set(tokenize_query(f"{new_node.title} {new_node.content}"))
    if not tokens:
        return None
    best_id: str | None = None
    best_score = 0.0
    for node in candidates:
        if node is None or getattr(node, "node_type", None) != new_node.node_type:
            continue  # 仅同类型可合并（data 合并 data / interaction 合并 interaction）
        nt = set(tokenize_query(f"{node.title} {node.content}"))
        if not nt:
            continue
        score = len(tokens & nt) / len(tokens | nt)
        if score > best_score:
            best_id = node.node_id
            best_score = score
    if best_id is not None and best_score >= settings.jaccard_threshold:
        return best_id
    return None


async def tool_apply_to_store(
    event_store: Any,
    graph_store: Any,
    proposal: Any,
    event_id: str,
    similar_nodes: list[Any] | None = None,
) -> list[str]:
    """将审核通过的图构建计划写入存储层（幂等：节点/边已存在则复用）。

    - merged_into（Gr 显式声明）：new_nodes 全部合并进已有节点，**不再新建**
      （修复旧实现「既合并又重复新建」导致的冗余节点）
    - 新建节点前做系统去重预检（A2）：与 similar_nodes 高度重合（Jaccard ≥ 阈值、
      同类型）→ 自动改道合并，不新建
    - 合并统一走 graph_store.merge_into（source_refs 并集 + 反向索引 + 落盘）
    """
    event = await event_store.get(event_id)
    c_hash = event["content_hash"] if event else ""
    similar = similar_nodes or []

    created: list[str] = []
    id_by_title: dict[str, str] = {}

    # ── 1) Gr 显式 merged_into：内容并入已有节点，不新建 ──
    merged = graph_store.get_node(proposal.merged_into) if proposal.merged_into else None
    if merged is not None:
        lines = [nc.content for nc in proposal.new_nodes if nc.content]
        conf = max((nc.confidence for nc in proposal.new_nodes), default=None)
        m = graph_store.merge_into(
            merged.node_id,
            event_id=event_id,
            content_hash=c_hash,
            content="\n".join(lines) if lines else None,
            confidence=conf,
        )
        if m is not None:
            await graph_store.upsert_node_fts(m.node_id, m.title, m.content)
            created.append(m.node_id)
            id_by_title = {nc.title: m.node_id for nc in proposal.new_nodes}

    # ── 2) 新建节点（含系统去重预检：重合 → 自动改道合并，不新建）──
    for nc in proposal.new_nodes:
        if proposal.merged_into:
            continue  # 已合并进 merged_into
        dup_id = find_redundant_node(graph_store, nc, similar)
        if dup_id is not None:
            m = graph_store.merge_into(
                dup_id,
                event_id=event_id,
                content_hash=c_hash,
                content=nc.content,
                confidence=nc.confidence,
            )
            if m is not None:
                await graph_store.upsert_node_fts(m.node_id, m.title, m.content)
                id_by_title[nc.title] = m.node_id
                created.append(m.node_id)
            continue
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

    # ── 3) 新建边（source/target 支持新节点 title 或已有 node_id）──
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
    graph_store: Any,
    proposal: Any,
    source_content: str,
    chunks: Any = None,
    similar_nodes: list[Any] | None = None,
) -> list[MetaCogIssue]:
    """来源锚定 / 边合法性 / 空节点 / 冗余节点 的本地逻辑检查。

    纯确定性检查，不调 LLM。有任一问题即返回 fail 级 issues。
    传入 chunks 时，额外校验 evidence_quote 至少属于某个 chunk.content（合并跨块可容忍）。
    传入 similar_nodes 时，校验 new_nodes 是否与已有节点高度重合（冗余节点硬规则）。
    """
    issues: list[MetaCogIssue] = []
    new_titles = {nc.title for nc in proposal.new_nodes}
    chunk_texts = [c.content for c in (chunks.chunks if chunks else [])]
    similar = similar_nodes or []

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
        elif quote and chunk_texts and not any(quote in t for t in chunk_texts):
            issues.append(
                MetaCogIssue(
                    type="hallucination",
                    description=f"evidence_quote 不属于任何 In 分块：{nc.title}",
                    suggestion="从所属分块的原文中逐字摘录",
                )
            )

    if similar:
        # 冗余节点硬规则（B2）：new_node 与已有相似节点词重叠 Jaccard ≥ 阈值且同类型
        # → 驳回并要求 Gr 显式 merged_into，从语义层抑制冗余，而非依赖执行层兜底改道
        for nc in proposal.new_nodes:
            dup_id = find_redundant_node(graph_store, nc, similar)
            if dup_id is not None:
                issues.append(
                    MetaCogIssue(
                        type="redundant_node",
                        description=f"新节点与已有节点高度重合：{nc.title}",
                        suggestion=f"合并到已有节点 {dup_id}（填 merged_into）而非新建",
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


def relevant_edges(graph_store: Any, proposal: Any, limit: int = 50) -> list[dict[str, Any]]:
    """冲突检测用的邻域边：优先取 new_edges 引用到的已有节点所参与的边；
    不足时补任意边作上下文，避免 Meta 无图上下文可判。"""
    ids: set[str] = set()
    for ec in proposal.new_edges:
        if graph_store.get_node(ec.source) is not None:
            ids.add(ec.source)
        if graph_store.get_node(ec.target) is not None:
            ids.add(ec.target)
    all_edges = graph_store.list_edges()
    filtered = [e for e in all_edges if e["source"] in ids or e["target"] in ids]
    if len(filtered) < 10:
        seen = set()
        for e in filtered:
            seen.add((e["source"], e["target"]))
        filtered += [
            e for e in all_edges
            if (e["source"], e["target"]) not in seen
        ][: 10 - len(filtered)]
    return filtered[:limit]


def empty_verdict(issues: list[MetaCogIssue]) -> MetaCogVerdict:
    return MetaCogVerdict(verdict="fail", issues=issues)


# ── 图维护（调整/合并/删改）：扫描候选 → 本地审核 → 执行 ──

# 维护候选的相似对阈值（低于 A2 写入时自动改道的 0.85：候选只是建议，
# 是否合并由 Gr/Meta 语义判断；0.85 是「近乎相同」直接拦，0.6 是「值得看」）
# 相似度用 overlap coefficient（交集/较短者）：无分词器下连续中文段是一个
# token，Jaccard 对「一段是另一段超集」的包容关系过严，overlap 更合适。
_MAINTENANCE_OVERLAP = 0.6
_MAINTENANCE_CANDIDATE_CAP = 30

# 节点压缩（data 概括压缩）候选阈值——确定性代理，真实语义由 Gr/Meta 判断。
# 溯源关联深重（多源证并入 → 内容累积成碎片）或内容冗长（单事件大段）的 data 节点。
_COMPRESS_MIN_REFS = 3       # 有效源证数：≥3 条事件并入 → 溯源关联深重
_COMPRESS_MIN_CONTENT = 500  # content 字符数：≥500 → 冗长，值得概括


def scan_maintenance_candidates(graph_store: Any) -> dict[str, list[dict]]:
    """确定性扫描图维护候选（无 LLM），供 Gr 决策：

    - merge_candidates：同类型节点对，词重叠 Jaccard ≥ 0.6
      （词桶优化：只比较共享词的节点对，避免全图 O(n²)）
    - zombie_nodes：无有效源证的节点（可删除候选；system 除外）
    - low_conf_isolated：confidence < 0.4 且无边的孤立节点（需判断）
    - compress_candidates：data 节点（非 system/interaction），溯源关联深重
      （有效源证 ≥ _COMPRESS_MIN_REFS）或内容冗长（≥ _COMPRESS_MIN_CONTENT）
    """
    from core.text_utils import tokenize_query

    buckets: dict[str, list[str]] = {}
    token_sets: dict[str, set[str]] = {}
    for nid, ndata in graph_store.graph.nodes(data="data"):
        if ndata is None:
            continue
        toks = set(tokenize_query(f"{ndata.title} {ndata.content}"))
        token_sets[nid] = toks
        for t in toks:
            buckets.setdefault(t, []).append(nid)

    seen: set[tuple[str, str]] = set()
    merge_candidates: list[dict] = []
    for nid, toks in token_sets.items():
        if not toks:
            continue
        node = graph_store.get_node(nid)
        if node is None:
            continue
        peers: set[str] = set()
        for t in toks:
            peers.update(buckets.get(t, []))
        for pid in peers:
            if pid == nid:
                continue
            key = tuple(sorted((nid, pid)))
            if key in seen:
                continue
            seen.add(key)
            pnode = graph_store.get_node(pid)
            if pnode is None or pnode.node_type != node.node_type:
                continue  # 仅同类型可合并
            ptoks = token_sets.get(pid, set())
            if not ptoks:
                continue
            overlap = len(toks & ptoks) / min(len(toks), len(ptoks))
            if overlap >= _MAINTENANCE_OVERLAP:
                # 内容更完整者作 target
                if len(node.content) >= len(pnode.content):
                    target_id, source_id = nid, pid
                else:
                    target_id, source_id = pid, nid
                merge_candidates.append({
                    "target_id": target_id,
                    "source_id": source_id,
                    "overlap": round(overlap, 3),
                    "target_title": graph_store.get_node(target_id).title,
                    "source_title": graph_store.get_node(source_id).title,
                })

    zombie_nodes: list[dict] = []
    low_conf_isolated: list[dict] = []
    for nid, ndata in graph_store.graph.nodes(data="data"):
        if ndata is None or ndata.node_type.value == "system":
            continue
        if not any(sr.valid for sr in ndata.source_refs):
            zombie_nodes.append({
                "node_id": nid,
                "title": ndata.title,
                "node_type": ndata.node_type.value,
                "refs": len(ndata.source_refs),
                "content": (ndata.content or "")[:200],
            })
        elif ndata.confidence < 0.4 and graph_store.graph.degree(nid) == 0:
            low_conf_isolated.append({
                "node_id": nid,
                "title": ndata.title,
                "confidence": ndata.confidence,
            })

    # 节点压缩候选：仅 data 节点（非 system/interaction），
    # 溯源关联深重（多有效源证）或内容冗长 → 可概括压缩（system 永不参与）
    compress_candidates: list[dict] = []
    for nid, ndata in graph_store.graph.nodes(data="data"):
        if ndata is None or ndata.node_type.value != "data":
            continue
        valid_refs = sum(1 for sr in ndata.source_refs if sr.valid)
        content_len = len(ndata.content or "")
        if valid_refs >= _COMPRESS_MIN_REFS or content_len >= _COMPRESS_MIN_CONTENT:
            compress_candidates.append({
                "node_id": nid,
                "title": ndata.title,
                "refs": valid_refs,
                "content_len": content_len,
                "content": (ndata.content or "")[:200],
            })

    return {
        "merge_candidates": merge_candidates[:_MAINTENANCE_CANDIDATE_CAP],
        "zombie_nodes": zombie_nodes[:_MAINTENANCE_CANDIDATE_CAP],
        "low_conf_isolated": low_conf_isolated[:_MAINTENANCE_CANDIDATE_CAP],
        "compress_candidates": compress_candidates[:_MAINTENANCE_CANDIDATE_CAP],
        "total_nodes": graph_store.total_nodes(),
    }


def run_maintenance_local_checks(graph_store: Any, plan: Any) -> list[MetaCogIssue]:
    """维护计划本地硬规则（无 LLM）：存在性 / 类型边界 / 删除保护。

    与协议保护对齐：system 永不参与；data 仅无有效源证可删；
    合并仅同类型；修改内容非空；压缩仅 data（概括非空、补边合法）。
    任何问题即 fail 级 issues。
    """
    issues: list[MetaCogIssue] = []
    for m in plan.merges:
        target = graph_store.get_node(m.target_id)
        if target is None:
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description=f"合并目标节点不存在：{m.target_id}",
                suggestion="删除该合并项",
            ))
            continue
        for sid in m.source_ids:
            src = graph_store.get_node(sid)
            if src is None:
                issues.append(MetaCogIssue(
                    type="illegal_edge",
                    description=f"合并源节点不存在：{sid}",
                    suggestion="删除该合并项",
                ))
            elif src.node_type != target.node_type:
                issues.append(MetaCogIssue(
                    type="illegal_edge",
                    description=f"合并类型不同：{target.title}({target.node_type.value})"
                                f" ← {src.title}({src.node_type.value})",
                    suggestion="仅同类型节点可合并",
                ))
            elif src.node_type.value == "system":
                issues.append(MetaCogIssue(
                    type="illegal_edge",
                    description="system 节点禁止参与合并",
                    suggestion="删除该合并项",
                ))
    for d in plan.deletes:
        node = graph_store.get_node(d.node_id)
        if node is None:
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description=f"删除目标节点不存在：{d.node_id}",
                suggestion="删除该项",
            ))
        elif node.node_type.value == "system":
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description="system 节点禁止删除",
                suggestion="删除该项",
            ))
        elif node.node_type.value == "data" and any(sr.valid for sr in node.source_refs):
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description=f"data 节点有有效源证，禁止删除：{node.title}",
                suggestion="删除该项",
            ))
    for u in plan.updates:
        node = graph_store.get_node(u.node_id)
        if node is None:
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description=f"修改目标节点不存在：{u.node_id}",
                suggestion="删除该项",
            ))
        elif node.node_type.value == "system":
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description="system 节点禁止修改",
                suggestion="删除该项",
            ))
        elif not (u.content or "").strip():
            issues.append(MetaCogIssue(
                type="empty_node",
                description=f"修改内容为空：{u.node_id}",
                suggestion="补充内容或删除该项",
            ))
    for e in plan.edge_removes:
        if not graph_store.get_edge(e.source, e.target):
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description=f"待删边不存在：{e.source}→{e.target}",
                suggestion="删除该项",
            ))
    for c in plan.compresses:
        node = graph_store.get_node(c.node_id)
        if node is None:
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description=f"压缩目标节点不存在：{c.node_id}",
                suggestion="删除该项",
            ))
            continue
        elif node.node_type.value == "system":
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description="system 节点禁止压缩",
                suggestion="删除该项",
            ))
        elif node.node_type.value == "interaction":
            issues.append(MetaCogIssue(
                type="illegal_edge",
                description=f"interaction 节点禁止压缩（仅 data 可概括）：{node.title}",
                suggestion="删除该项",
            ))
        elif not (c.content or "").strip():
            issues.append(MetaCogIssue(
                type="empty_node",
                description=f"压缩内容为空：{c.node_id}",
                suggestion="补充概括后内容或删除该项",
            ))
        for e in c.new_edges:
            if graph_store.get_node(e.source) is None or graph_store.get_node(e.target) is None:
                issues.append(MetaCogIssue(
                    type="illegal_edge",
                    description=f"压缩补边节点不存在：{e.source}→{e.target}",
                    suggestion="删除该边或改用已有节点",
                ))
    return issues


async def tool_apply_maintenance(
    event_store: Any, graph_store: Any, plan: Any
) -> dict[str, Any]:
    """执行审核通过的图维护计划（合并/删除/修改/删边/压缩），返回执行统计。

    - 合并：graph_store.merge_nodes（target 吸收源证/内容/边迁移后删 source）
    - 删除：执行层再兜底保护（system 跳过；data 有有效源证跳过）
    - 修改：interaction 覆盖内容；data 转为追加行（不得概括，证据锚定精神）
    - 删边：按 (source, target)
    - 压缩：仅 data 可否概括（覆盖 content + 可选精炼 title + 补边）；
      source_refs 保留不动（溯源锚定不破坏）；补边 evidence 取该节点首个有效源证事件
    - FTS 同步 + flush 落盘
    """
    stats: dict[str, Any] = {
        "merged": [], "deleted": [], "updated": [],
        "edges_removed": [], "compressed": [],
    }

    for m in plan.merges:
        removed = graph_store.merge_nodes(m.target_id, m.source_ids)
        if removed:
            target = graph_store.get_node(m.target_id)
            await graph_store.upsert_node_fts(target.node_id, target.title, target.content)
            for sid in removed:
                await graph_store.delete_node_fts(sid)
            stats["merged"].append({"target": m.target_id, "sources": removed})

    for d in plan.deletes:
        node = graph_store.get_node(d.node_id)
        if node is None or node.node_type.value == "system":
            continue
        if node.node_type.value == "data" and any(sr.valid for sr in node.source_refs):
            continue
        graph_store.remove_node(d.node_id)
        await graph_store.delete_node_fts(d.node_id)
        stats["deleted"].append(d.node_id)

    for u in plan.updates:
        node = graph_store.get_node(u.node_id)
        if node is None or node.node_type.value == "system":
            continue
        changed = False
        if node.node_type.value == "data":
            # data 只允许追加（不得概括）；空追加或内容已存在时不视为更新
            if u.content and u.content not in node.content:
                graph_store.update_node(
                    u.node_id, content=(node.content + "\n" + u.content).strip()
                )
                changed = True
        else:
            graph_store.update_node(u.node_id, content=u.content)
            changed = True
        if not changed:
            continue
        updated = graph_store.get_node(u.node_id)
        await graph_store.upsert_node_fts(u.node_id, updated.title, updated.content)
        stats["updated"].append(u.node_id)

    for e in plan.edge_removes:
        if graph_store.remove_edge(e.source, e.target):
            stats["edges_removed"].append(f"{e.source}→{e.target}")

    for c in plan.compresses:
        node = graph_store.get_node(c.node_id)
        if node is None or node.node_type.value != "data":
            continue  # 兜底：仅 data 可压缩（system/interaction 跳过）
        # 概括覆盖 content + 可选精炼 title；source_refs 不变（溯源锚定不破坏）
        graph_store.update_node(
            c.node_id, content=c.content, title=(c.title or None)
        )
        # 补充关系：把概括后可能丢失的隐含关系显式化为边
        evidence = next(
            (sr.event_id for sr in node.source_refs if sr.valid), ""
        )
        for e in c.new_edges:
            src_ok = graph_store.get_node(e.source) is not None
            tgt_ok = graph_store.get_node(e.target) is not None
            if src_ok and tgt_ok:
                graph_store.add_edge(GraphEdge(
                    source=e.source, target=e.target,
                    relation=e.relation, evidence_event_id=evidence,
                ))
        compressed = graph_store.get_node(c.node_id)
        await graph_store.upsert_node_fts(c.node_id, compressed.title, compressed.content)
        stats["compressed"].append(c.node_id)

    await graph_store.flush()
    return stats
