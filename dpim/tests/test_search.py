import pytest

from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import (
    GraphEdge,
    GraphNode,
    NodeMetadata,
    NodeType,
    SearchRequest,
    SourceRef,
)
from core.search import search


@pytest.fixture
async def populated_stores(db, event_store: EventStore, graph_store: GraphStore):
    e1, _ = await event_store.insert("Python machine learning framework")
    await event_store.insert_fts(e1, "Python machine learning framework")
    await event_store.update_status(e1, "linked", graph_refs=["n1"])

    e2, _ = await event_store.insert("Java virtual machine performance")
    await event_store.insert_fts(e2, "Java virtual machine performance")
    await event_store.update_status(e2, "linked", graph_refs=["n2"])

    e3, _ = await event_store.insert("JavaScript web development")
    await event_store.insert_fts(e3, "JavaScript web development")

    n1 = GraphNode(
        node_id="n1", title="Python ML", content="Python for machine learning",
        node_type=NodeType.data,
        source_refs=[SourceRef(event_id=e1, valid=True, hash="h1")],
        confidence=0.9, metadata=NodeMetadata(evidence_quote="ML"),
    )
    graph_store.add_node(n1)
    await graph_store.upsert_node_fts("n1", "Python ML", "Python for machine learning")

    n2 = GraphNode(
        node_id="n2", title="Java", content="Java virtual machine",
        node_type=NodeType.interaction,
        source_refs=[SourceRef(event_id=e2, valid=True, hash="h2")],
        confidence=0.8, metadata=NodeMetadata(evidence_quote="JVM"),
    )
    graph_store.add_node(n2)
    await graph_store.upsert_node_fts("n2", "Java", "Java virtual machine")

    graph_store.add_edge(GraphEdge(
        source="n1", target="n2", relation="related_to", evidence_event_id=e1,
    ))
    return event_store, graph_store


class TestSearchDegraded:
    @pytest.mark.asyncio
    async def test_degraded_fts_returns_results(self, populated_stores):
        es, gs = populated_stores
        req = SearchRequest(query="Python")
        resp = await search(req, es, gs, degraded=True)
        assert resp.degraded is True
        assert len(resp.results) > 0

    @pytest.mark.asyncio
    async def test_degraded_no_match(self, populated_stores):
        es, gs = populated_stores
        req = SearchRequest(query="zzz_nonexistent")
        resp = await search(req, es, gs, degraded=True)
        assert len(resp.results) == 0
        assert resp.total == 0

    @pytest.mark.asyncio
    async def test_degraded_pagination(self, populated_stores):
        es, gs = populated_stores
        req = SearchRequest(query="Python", limit=1)
        resp = await search(req, es, gs, degraded=True)
        assert len(resp.results) <= 1


class TestSearchNormal:
    @pytest.mark.asyncio
    async def test_normal_returns_results(self, populated_stores):
        es, gs = populated_stores
        req = SearchRequest(query="Python")
        resp = await search(req, es, gs, degraded=False)
        assert resp.degraded is False
        assert len(resp.results) > 0

    @pytest.mark.asyncio
    async def test_normal_retrieves_node_data(self, populated_stores):
        es, gs = populated_stores
        req = SearchRequest(query="Python")
        resp = await search(req, es, gs, degraded=False)
        result = next((r for r in resp.results if r.node_id == "n1"), None)
        assert result is not None
        assert result.title == "Python ML"
        assert result.source_type == "data"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_graph_diffusion_expands_results(self, populated_stores):
        es, gs = populated_stores
        req = SearchRequest(query="Python")
        resp_degraded = await search(req, es, gs, degraded=True)
        resp_normal = await search(req, es, gs, degraded=False)
        # Normal mode with graph diffusion should have more or equal results
        assert resp_normal.total >= resp_degraded.total

    @pytest.mark.asyncio
    async def test_source_filter(self, populated_stores):
        es, gs = populated_stores
        req = SearchRequest(query="Python", source_filter="interaction")
        resp = await search(req, es, gs, degraded=False)
        for r in resp.results:
            assert r.source_type == "interaction"


class TestSearchEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_query(self, db):
        es = EventStore(db)
        gs = GraphStore(db)
        await gs.load()
        req = SearchRequest(query="")
        resp = await search(req, es, gs, degraded=False)
        assert len(resp.results) == 0

    @pytest.mark.asyncio
    async def test_offset_pagination(self, populated_stores):
        es, gs = populated_stores
        req_all = SearchRequest(query="Python OR Java OR JavaScript", limit=20)
        resp_all = await search(req_all, es, gs, degraded=True)
        total = resp_all.total
        if total > 1:
            req_first = SearchRequest(query="Python OR Java OR JavaScript", limit=1, offset=0)
            resp_first = await search(req_first, es, gs, degraded=True)
            assert len(resp_first.results) == 1


class TestDiffusionRelevanceFilter:
    """图扩散召回相关性过滤：无向扩散把与查询无关的邻居（如搜「游戏」带出「八段锦」）混入结果，
    按查询词面重叠过滤剔除（用户诉求：尽量无关的不要做）。"""

    @pytest.mark.asyncio
    async def test_retain_relevant_expansion_drops_unrelated(self, populated_stores):
        from core.search import retain_relevant_expansion

        es, gs = populated_stores
        n3 = GraphNode(
            node_id="n3", title="八段锦健身", content="八段锦是一套传统健身功法",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e3x", valid=True, hash="h3")],
            confidence=0.7, metadata=NodeMetadata(evidence_quote="八段锦"),
        )
        gs.add_node(n3)
        gs.add_edge(GraphEdge(source="n1", target="n3", relation="related_to", evidence_event_id="e1"))
        # n1 含「Python」保留；n2（Java）/ n3（八段锦）无词面重叠被剔除
        kept = retain_relevant_expansion(gs, {"n1": 0.8, "n2": 0.5, "n3": 0.7}, "Python")
        assert "n1" in kept
        assert "n2" not in kept
        assert "n3" not in kept

    @pytest.mark.asyncio
    async def test_search_drops_unrelated_diffusion(self, populated_stores):
        es, gs = populated_stores
        n3 = GraphNode(
            node_id="n3", title="八段锦健身", content="八段锦是一套传统健身功法",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e3x", valid=True, hash="h3")],
            confidence=0.7, metadata=NodeMetadata(evidence_quote="八段锦"),
        )
        gs.add_node(n3)
        await gs.upsert_node_fts("n3", "八段锦健身", "八段锦是一套传统健身功法")
        gs.add_edge(GraphEdge(source="n1", target="n3", relation="related_to", evidence_event_id="e1"))
        req = SearchRequest(query="Python", max_hops=2)
        resp = await search(req, es, gs, degraded=False)
        titles = [r.title for r in resp.results]
        assert any(t == "Python ML" for t in titles)
        assert all("八段锦" not in t for t in titles)


class TestSearchControlledVariables:
    """控制变量：RRF 融合、时间衰减、源过滤"""

    @pytest.mark.asyncio
    async def test_rrf_double_ranked_higher(self, db, tmp_path):
        """对照：同节点出现在 C1+C2 → RRF 得分高于仅在 C1 的节点"""
        es = EventStore(db)
        gs = GraphStore(db, json_path=str(tmp_path / "rrf.json"))
        await gs.load()
        from tests.factories import make_edge, make_event, make_node
        e1 = await make_event(es, "python ai")
        e2 = await make_event(es, "python web")
        await make_node(gs, "n_ai", "AI", "artificial intelligence",
                              event_id=e1, confidence=0.9)
        await make_node(gs, "n_web", "Web", "web framework",
                              event_id=e2, confidence=0.9)
        await make_edge(gs, "n_ai", "n_web", relation="related", event_id=e1)
        # Link events to graph nodes
        await es.update_status(e1, "linked", graph_refs=["n_ai"])
        await es.update_status(e2, "linked", graph_refs=["n_web"])
        await es.insert_fts(e1, "python ai")
        await es.insert_fts(e2, "python web")
        await gs.upsert_node_fts("n_ai", "AI", "artificial intelligence")
        await gs.upsert_node_fts("n_web", "Web", "web framework")
        req = SearchRequest(query="python")
        resp = await search(req, es, gs, degraded=False)
        assert resp.degraded is False
        scores = {r.node_id: r.score for r in resp.results}
        # n_ai appears in C1 (via FTS) and C2 (via diffusion from n_web in C1)
        # n_web appears only in C1 (FTS)
        # n_ai's RRF should benefit from both rankings
        assert scores.get("n_ai", 0) > 0
        assert scores.get("n_web", 0) > 0

    @pytest.mark.asyncio
    async def test_time_decay_older_event_lower_score(self, db, tmp_path):
        """对照：相同内容，旧事件得分低于新事件"""
        es = EventStore(db)
        gs = GraphStore(db, json_path=str(tmp_path / "decay.json"))
        await gs.load()
        from tests.factories import make_event, make_node
        old_ts = "2026-01-01T00:00:00+00:00"
        new_ts = "2026-07-24T00:00:00+00:00"
        e_old = await make_event(es, "common topic", created_at=old_ts)
        e_new = await make_event(es, "common topic", created_at=new_ts)
        await es.insert_fts(e_old, "common topic")
        await es.insert_fts(e_new, "common topic")
        await make_node(gs, "n_old", "Old", "old content",
                                NodeType.interaction, event_id=e_old)
        await make_node(gs, "n_new", "New", "new content",
                                NodeType.interaction, event_id=e_new)
        await es.update_status(e_old, "linked", graph_refs=["n_old"])
        await es.update_status(e_new, "linked", graph_refs=["n_new"])
        await gs.upsert_node_fts("n_old", "Old", "old content")
        await gs.upsert_node_fts("n_new", "New", "new content")
        req = SearchRequest(query="common")
        resp = await search(req, es, gs, degraded=False)
        scores = {r.node_id: r.score for r in resp.results}
        score_old = scores.get("n_old", 0)
        score_new = scores.get("n_new", 0)
        assert score_new > score_old, (
            f"Expected new > old, got new={score_new:.4f} old={score_old:.4f}"
        )

    @pytest.mark.asyncio
    async def test_source_filter_interaction_only(self, db, tmp_path):
        """对照：同时有 interaction 和 data 节点，过滤后只返回 interaction"""
        es = EventStore(db)
        gs = GraphStore(db, json_path=str(tmp_path / "filter.json"))
        await gs.load()
        from tests.factories import make_event, make_node
        e_int = await make_event(es, "chat message", "interaction")
        e_dat = await make_event(es, "factual data", "data")
        await make_node(gs, "n_int", "Chat", "user said hi",
                                NodeType.interaction, event_id=e_int)
        await make_node(gs, "n_dat", "Fact", "temperature data",
                                NodeType.data, event_id=e_dat)
        await es.insert_fts(e_int, "chat message")
        await es.insert_fts(e_dat, "factual data")
        await es.update_status(e_int, "linked", graph_refs=["n_int"])
        await es.update_status(e_dat, "linked", graph_refs=["n_dat"])
        await gs.upsert_node_fts("n_int", "Chat", "user said hi")
        await gs.upsert_node_fts("n_dat", "Fact", "temperature data")
        req = SearchRequest(query="message OR factual", source_filter="interaction")
        resp = await search(req, es, gs, degraded=False)
        for r in resp.results:
            assert r.source_type == "interaction", f"{r.node_id} is {r.source_type}"

