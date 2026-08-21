
import json

import pytest

from core.graph_store import GraphStore
from core.models import GraphEdge, GraphNode, NodeMetadata, NodeType, SourceRef


@pytest.fixture
async def graph_store_with_data(graph_store: GraphStore):
    """Pre-populated graph store with sample data."""
    node1 = GraphNode(
        node_id="n1",
        title="Python",
        content="A programming language",
        node_type=NodeType.data,
        source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
        confidence=0.9,
        metadata=NodeMetadata(evidence_quote="Python is a programming language"),
    )
    node2 = GraphNode(
        node_id="n2",
        title="Async",
        content="Asynchronous programming",
        node_type=NodeType.interaction,
        source_refs=[SourceRef(event_id="e2", valid=True, hash="h2")],
        confidence=0.8,
        metadata=NodeMetadata(evidence_quote="async programming concepts"),
    )
    node3 = GraphNode(
        node_id="n3",
        title="SQLite",
        content="Embedded database engine",
        node_type=NodeType.data,
        source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
        confidence=0.7,
        metadata=NodeMetadata(evidence_quote="SQLite is embedded"),
    )
    graph_store.add_node(node1)
    graph_store.add_node(node2)
    graph_store.add_node(node3)
    graph_store.add_edge(GraphEdge(
        source="n1", target="n2",
        relation="has_concept",
        evidence_event_id="e1",
    ))
    graph_store.add_edge(GraphEdge(
        source="n1", target="n3",
        relation="related_to",
        evidence_event_id="e1",
    ))
    return graph_store


class TestGraphStoreNodeCRUD:
    @pytest.mark.asyncio
    async def test_add_and_get_node(self, graph_store: GraphStore):
        node = GraphNode(
            node_id="n1",
            title="Test",
            content="content",
            node_type=NodeType.system,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=1.0,
            metadata=NodeMetadata(evidence_quote="test"),
        )
        graph_store.add_node(node)
        retrieved = graph_store.get_node("n1")
        assert retrieved is not None
        assert retrieved.title == "Test"
        assert retrieved.node_type == NodeType.system

    @pytest.mark.asyncio
    async def test_get_nonexistent_node(self, graph_store: GraphStore):
        assert graph_store.get_node("nothing") is None

    @pytest.mark.asyncio
    async def test_remove_node(self, graph_store: GraphStore):
        node = GraphNode(
            node_id="remove_me",
            title="Gone",
            content="bye",
            node_type=NodeType.interaction,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=0.5,
            metadata=NodeMetadata(evidence_quote="bye"),
        )
        graph_store.add_node(node)
        assert graph_store.remove_node("remove_me") is True
        assert graph_store.get_node("remove_me") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_node(self, graph_store: GraphStore):
        assert graph_store.remove_node("nothing") is False


class TestGraphStoreEdgeCRUD:
    @pytest.mark.asyncio
    async def test_add_and_get_edge(self, graph_store_with_data: GraphStore):
        edge = graph_store_with_data.get_edge("n1", "n2")
        assert edge is not None
        assert edge.relation == "has_concept"
        assert edge.evidence_event_id == "e1"

    @pytest.mark.asyncio
    async def test_remove_edge(self, graph_store_with_data: GraphStore):
        assert graph_store_with_data.remove_edge("n1", "n2") is True
        assert graph_store_with_data.get_edge("n1", "n2") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_edge(self, graph_store_with_data: GraphStore):
        assert graph_store_with_data.remove_edge("nothing", "nowhere") is False


class TestGraphStoreReverseIndex:
    @pytest.mark.asyncio
    async def test_get_nodes_for_event(self, graph_store_with_data: GraphStore):
        nodes = graph_store_with_data.get_nodes_for_event("e1")
        assert "n1" in nodes
        assert "n3" in nodes

    @pytest.mark.asyncio
    async def test_remove_node_clears_index(self, graph_store_with_data: GraphStore):
        graph_store_with_data.remove_node("n3")
        nodes = graph_store_with_data.get_nodes_for_event("e1")
        assert "n3" not in nodes

    @pytest.mark.asyncio
    async def test_invalidate_source_ref(self, graph_store_with_data: GraphStore):
        graph_store_with_data.invalidate_source_ref("e1")
        node = graph_store_with_data.get_node("n1")
        ref = next(r for r in node.source_refs if r.event_id == "e1")
        assert ref.valid is False


class TestGraphStorePersistence:
    @pytest.mark.asyncio
    async def test_load_nonexistent_file(self, graph_store: GraphStore):
        assert graph_store.graph.number_of_nodes() == 0

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, db, tmp_path):
        json_path = tmp_path / "graph.json"
        gs1 = GraphStore(db, json_path=str(json_path))
        await gs1.load()
        node = GraphNode(
            node_id="persist",
            title="Persist Me",
            content="data",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=0.6,
            metadata=NodeMetadata(evidence_quote="persist"),
        )
        gs1.add_node(node)
        gs1.add_edge(GraphEdge(
            source="persist", target="persist",
            relation="self", evidence_event_id="e1",
        ))
        await gs1.save()

        gs2 = GraphStore(db, json_path=str(json_path))
        await gs2.load()
        assert gs2.get_node("persist") is not None
        assert gs2.get_node("persist").title == "Persist Me"
        assert gs2.get_edge("persist", "persist") is not None

    @pytest.mark.asyncio
    async def test_dirty_flag(self, graph_store: GraphStore):
        assert graph_store.dirty is False
        node = GraphNode(
            node_id="dirty_test",
            title="Dirty",
            content="c",
            node_type=NodeType.interaction,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=0.5,
            metadata=NodeMetadata(evidence_quote="dirty"),
        )
        graph_store.add_node(node)
        assert graph_store.dirty is True

    @pytest.mark.asyncio
    async def test_load_corrupt_json_falls_back_to_empty(self, db, tmp_path):
        """容错：graph.json 损坏（手滑删括号）→ 空图启动，不崩溃"""
        json_path = tmp_path / "graph.json"
        json_path.write_text('{"nodes": {broken', encoding="utf-8")
        gs = GraphStore(db, json_path=str(json_path))
        await gs.load()  # 不抛异常
        assert gs.graph.number_of_nodes() == 0

    @pytest.mark.asyncio
    async def test_load_corrupt_json_recovers_from_backup(self, db, tmp_path):
        """容错：主文件损坏 → 自动从 .json.bak 快照恢复"""
        json_path = tmp_path / "graph.json"
        # 先正常保存一次生成 .bak
        gs1 = GraphStore(db, json_path=str(json_path))
        await gs1.load()
        node = GraphNode(
            node_id="backup_me", title="Backup", content="c",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=0.5, metadata=NodeMetadata(evidence_quote="b"),
        )
        gs1.add_node(node)
        await gs1.save()
        # 主文件写坏，.bak 完好
        json_path.write_text("truncated garbage", encoding="utf-8")
        gs2 = GraphStore(db, json_path=str(json_path))
        await gs2.load()
        assert gs2.get_node("backup_me") is not None

    @pytest.mark.asyncio
    async def test_load_both_corrupt_starts_empty(self, db, tmp_path):
        """容错：主文件与 .bak 均损坏 → 空图启动，不崩溃"""
        json_path = tmp_path / "graph.json"
        json_path.write_text('{"nodes": {', encoding="utf-8")
        json_path.with_suffix(".json.bak").write_text("also broken", encoding="utf-8")
        gs = GraphStore(db, json_path=str(json_path))
        await gs.load()
        assert gs.graph.number_of_nodes() == 0

    @pytest.mark.asyncio
    async def test_load_success_creates_backup(self, db, tmp_path):
        """容错：正常加载后留存 .json.bak 快照，供下次损坏时恢复"""
        json_path = tmp_path / "graph.json"
        json_path.write_text('{"nodes": {}, "edges": []}', encoding="utf-8")
        gs = GraphStore(db, json_path=str(json_path))
        await gs.load()
        assert json_path.with_suffix(".json.bak").exists()

    @pytest.mark.asyncio
    async def test_flush_writes_when_dirty(self, db, tmp_path):
        """flush 语义：有脏位即写盘（替代旧防抖阈值，杜绝未达阈值不落盘）。"""
        json_path = tmp_path / "graph.json"
        gs1 = GraphStore(db, json_path=str(json_path))
        await gs1.load()
        node = GraphNode(
            node_id="f1", title="Flush", content="data",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=0.5, metadata=NodeMetadata(evidence_quote="flush"),
        )
        gs1.add_node(node)
        await gs1.flush()  # 仅 1 次修改也立即落盘
        assert json_path.exists()

        gs2 = GraphStore(db, json_path=str(json_path))
        await gs2.load()
        assert gs2.get_node("f1") is not None

    @pytest.mark.asyncio
    async def test_update_node_marks_dirty_and_persists(self, db, tmp_path):
        """修改节点必须标记脏位并落盘：save 后重载可见（防静默丢失）。"""
        json_path = tmp_path / "graph.json"
        gs1 = GraphStore(db, json_path=str(json_path))
        await gs1.load()
        gs1.add_node(GraphNode(
            node_id="upd", title="Before", content="old",
            node_type=NodeType.interaction,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=0.5, metadata=NodeMetadata(evidence_quote="old"),
        ))
        await gs1.flush()
        updated = gs1.update_node("upd", content="new", confidence=0.7)
        assert updated is not None
        assert gs1.dirty is True  # update_node 必须标记脏位
        await gs1.save()

        gs2 = GraphStore(db, json_path=str(json_path))
        await gs2.load()
        node = gs2.get_node("upd")
        assert node.content == "new"
        assert node.confidence == 0.7

    @pytest.mark.asyncio
    async def test_update_node_nonexistent_returns_none(self, graph_store: GraphStore):
        assert graph_store.update_node("nothing", content="x") is None

    @pytest.mark.asyncio
    async def test_load_rebuilds_node_fts(self, db, tmp_path):
        """加载后 node_fts 以内存图为唯一真源重建：清残留、补新节点。

        手动编辑 graph.json 或备份恢复后，全文索引与图层保持一致。
        """
        json_path = tmp_path / "graph.json"
        json_path.write_text(json.dumps({
            "nodes": {
                "n_manual": {
                    "node_id": "n_manual", "title": "手工节点", "content": "手动编辑加入",
                    "node_type": "data",
                    "source_refs": [{"event_id": "e1", "valid": True, "hash": "h1"}],
                    "confidence": 0.8,
                    "metadata": {"evidence_quote": "手动"},
                }
            },
            "edges": [],
        }, ensure_ascii=False), encoding="utf-8")
        # 预置一条与图不一致的脏索引（模拟旧残留）
        gs1 = GraphStore(db, json_path=str(json_path))
        await gs1.load()
        await gs1.upsert_node_fts("ghost", "幽灵", "应被清除")
        await gs1.rebuild_node_fts()
        results = await gs1.search_node_fts("幽灵")
        assert len(results) == 0  # 脏索引已清
        results = await gs1.search_node_fts("手工")
        assert len(results) == 1
        assert results[0]["node_id"] == "n_manual"  # 新节点可检索

    @pytest.mark.asyncio
    async def test_clear_all_then_rebuild_fts_empty(self, graph_store: GraphStore):
        """清空图谱后重建 node_fts：旧节点检索不到。"""
        await graph_store.upsert_node_fts("old", "旧节点", "内容")
        graph_store.clear_all()
        await graph_store.rebuild_node_fts()
        results = await graph_store.search_node_fts("旧节点")
        assert len(results) == 0


class TestGraphStoreMerge:
    """merge_into 统一合并：source_refs 并集 + 反向索引 + 内容追加 + 置信度 max"""

    @pytest.mark.asyncio
    async def test_merge_adds_source_ref_and_reverse_index(self, graph_store: GraphStore):
        """合并必须补 source_refs 与反向索引（否则删除事件时该节点源证不失效）。"""
        from tests.factories import make_node
        await make_node(graph_store, "m1", "Python异步", "基础概念", event_id="e1")
        node = graph_store.merge_into("m1", event_id="e2", content_hash="h2")
        assert node is not None
        assert {sr.event_id for sr in node.source_refs} == {"e1", "e2"}
        assert "m1" in graph_store.get_nodes_for_event("e2")

    @pytest.mark.asyncio
    async def test_merge_duplicate_event_id_ignored(self, graph_store: GraphStore):
        from tests.factories import make_node
        await make_node(graph_store, "m1", "T", "c", event_id="e1")
        graph_store.merge_into("m1", event_id="e1", content_hash="h2")
        node = graph_store.get_node("m1")
        assert len(node.source_refs) == 1

    @pytest.mark.asyncio
    async def test_merge_appends_content_and_max_confidence(self, graph_store: GraphStore):
        from tests.factories import make_node
        await make_node(graph_store, "m1", "T", "旧内容", event_id="e1", confidence=0.5)
        graph_store.merge_into(
            "m1", event_id="e2", content_hash="h2",
            content="新内容", confidence=0.9,
        )
        node = graph_store.get_node("m1")
        assert "新内容" in node.content
        assert node.confidence == 0.9
        # 整段重复内容不追加
        graph_store.merge_into("m1", event_id="e3", content_hash="h3", content="新内容")
        assert node.content.count("新内容") == 1
        # confidence 只升不降
        graph_store.merge_into("m1", event_id="e4", content_hash="h4", confidence=0.3)
        assert node.confidence == 0.9

    @pytest.mark.asyncio
    async def test_merge_nonexistent_returns_none(self, graph_store: GraphStore):
        assert graph_store.merge_into("nothing", event_id="e1") is None

    @pytest.mark.asyncio
    async def test_merge_persists_after_flush(self, db, tmp_path):
        """合并后 flush 落盘：重载可见（防静默丢失）。"""
        json_path = tmp_path / "graph.json"
        gs1 = GraphStore(db, json_path=str(json_path))
        await gs1.load()
        gs1.add_node(GraphNode(
            node_id="m1", title="T", content="c",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=0.5, metadata=NodeMetadata(evidence_quote="c"),
        ))
        gs1.merge_into("m1", event_id="e2", content_hash="h2", content="追加内容")
        await gs1.flush()

        gs2 = GraphStore(db, json_path=str(json_path))
        await gs2.load()
        node = gs2.get_node("m1")
        assert "追加内容" in node.content
        assert {sr.event_id for sr in node.source_refs} == {"e1", "e2"}


class TestGraphStoreEgoGraph:
    @pytest.mark.asyncio
    async def test_ego_graph_returns_neighbors(self, graph_store_with_data: GraphStore):
        result = graph_store_with_data.ego_graph(["n1"], hops=1)
        assert "n2" in result
        assert "n3" in result

    @pytest.mark.asyncio
    async def test_ego_graph_scoring(self, graph_store_with_data: GraphStore):
        result = graph_store_with_data.ego_graph(["n1"], hops=1)
        assert result["n2"] == 0.5
        assert result["n3"] == 0.5

    @pytest.mark.asyncio
    async def test_ego_graph_2_hops(self, graph_store_with_data: GraphStore):
        # n1 -> n2, n1 -> n3
        # add n4 connected to n2
        n4 = GraphNode(
            node_id="n4",
            title="Deep",
            content="far away",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e3", valid=True, hash="h3")],
            confidence=0.5,
            metadata=NodeMetadata(evidence_quote="deep"),
        )
        graph_store_with_data.add_node(n4)
        graph_store_with_data.add_edge(GraphEdge(
            source="n2", target="n4",
            relation="extends", evidence_event_id="e3",
        ))
        result = graph_store_with_data.ego_graph(["n1"], hops=2)
        assert "n4" in result
        # n2 is 1 hop from n1, n4 is 2 hops from n1 via n2
        assert result["n4"] == 1.0 / 3

    @pytest.mark.asyncio
    async def test_ego_graph_reverse_hop_reachable(self, graph_store_with_data: GraphStore):
        """双向扩散：n1→n2 出边，从 n2（仅入边邻居）也能跳回 n1。

        检索召回不区分边方向；方向语义仍在边数据/前端展示中。
        """
        result = graph_store_with_data.ego_graph(["n2"], hops=1)
        assert "n1" in result  # 反向（入边）邻居可达
        assert result["n1"] == 0.5

    @pytest.mark.asyncio
    async def test_ego_graph_nonexistent_seed(self, graph_store: GraphStore):
        result = graph_store.ego_graph(["no_such_node"], hops=2)
        assert result == {}


class TestGraphStoreStats:
    @pytest.mark.asyncio
    async def test_total_nodes(self, graph_store_with_data: GraphStore):
        assert graph_store_with_data.total_nodes() == 3

    @pytest.mark.asyncio
    async def test_node_counts_by_type(self, graph_store_with_data: GraphStore):
        counts = graph_store_with_data.node_counts_by_type()
        assert counts["data"] == 2
        assert counts["interaction"] == 1
        assert counts["system"] == 0


class TestGraphStoreNodeFTS:
    @pytest.mark.asyncio
    async def test_upsert_and_search(self, graph_store: GraphStore):
        await graph_store.upsert_node_fts("n1", "Python", "A programming language")
        await graph_store.upsert_node_fts("n2", "Java", "Another language")
        results = await graph_store.search_node_fts("Python")
        assert len(results) == 1
        assert results[0]["node_id"] == "n1"

    @pytest.mark.asyncio
    async def test_delete_from_fts(self, graph_store: GraphStore):
        await graph_store.upsert_node_fts("n_del", "Delete", "test")
        await graph_store.delete_node_fts("n_del")
        results = await graph_store.search_node_fts("Delete")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_fts_no_match(self, graph_store: GraphStore):
        results = await graph_store.search_node_fts("zzz_not_there")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_like_fallback_title_priority(self, graph_store: GraphStore):
        """对照：中文 LIKE 降级时标题匹配优先于内容匹配"""
        from tests.factories import make_node
        await make_node(graph_store, "n_title", "异步编程入门", "无相关内容", event_id="e1")
        await make_node(graph_store, "n_content", "其他标题", "我学习异步编程", event_id="e2")
        await graph_store.upsert_node_fts("n_title", "异步编程入门", "无相关内容")
        await graph_store.upsert_node_fts("n_content", "其他标题", "我学习异步编程")
        results = await graph_store.search_node_fts("异步编程")
        # FTS5 对中文整串不命中 → 走 LIKE 降级
        assert len(results) == 2
        assert results[0]["node_id"] == "n_title"  # 标题命中排前
        assert results[1]["node_id"] == "n_content"
        assert results[0]["rank"] < results[1]["rank"]

    @pytest.mark.asyncio
    async def test_like_multi_token_ranking(self, graph_store: GraphStore):
        """多关键词降级：命中词数多的节点排前。"""
        from tests.factories import make_node
        # 不写 node_fts：FTS5 无命中直接走降级遍历内存图
        await make_node(graph_store, "n1", "Python 异步", "异步编程教程", event_id="e1")
        await make_node(graph_store, "n2", "Python 教程", "基础内容", event_id="e2")
        results = await graph_store.search_node_fts("异步 教程")
        assert len(results) == 2
        # n1：异步(标题) + 教程(内容) = 2 词；n2：仅 教程(标题) = 1 词
        assert results[0]["node_id"] == "n1"
        assert results[1]["node_id"] == "n2"


class TestGraphStoreControlledVariables:
    """控制变量：置信度排序、扩散跳数对照、多节点共享事件"""

    @pytest.mark.asyncio
    async def test_confidence_scores_affect_node_data(self, db):
        """对照：高置信度节点 vs 低置信度节点，数据保留完整"""
        from tests.factories import make_node
        gs = GraphStore(db, json_path=":memory:")
        await gs.load()
        await make_node(gs, "high", "High", "important", confidence=0.95)
        await make_node(gs, "low", "Low", "trivial", confidence=0.15)
        assert gs.get_node("high").confidence == 0.95
        assert gs.get_node("low").confidence == 0.15

    @pytest.mark.asyncio
    async def test_ego_graph_hop_distance_controls_score(self, graph_store_with_data):
        """对照：1 跳邻居得分 0.5，2 跳邻居得分 0.33"""
        n4 = GraphNode(
            node_id="n4", title="Deep", content="far",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e3", valid=True, hash="h3")],
            confidence=0.5,
            metadata=NodeMetadata(evidence_quote="deep"),
        )
        graph_store_with_data.add_node(n4)
        graph_store_with_data.add_edge(GraphEdge(
            source="n2", target="n4", relation="extends", evidence_event_id="e3",
        ))
        result = graph_store_with_data.ego_graph(["n1"], hops=2)
        assert result["n2"] == 0.5
        assert result["n4"] == 1.0 / 3

    @pytest.mark.asyncio
    async def test_multi_event_source_ref_all_valid(self, graph_store):
        """对照：节点关联 2 个事件，删除一个后另一个仍保持 valid"""
        from tests.factories import make_node
        n = await make_node(graph_store, "multi", "Multi", "content",
                            event_id="e_a")
        n.source_refs.append(SourceRef(event_id="e_b", valid=True, hash="h2"))
        graph_store.graph.nodes["multi"]["data"] = n
        graph_store._rebuild_reverse_index()
        graph_store.invalidate_source_ref("e_a")
        node = graph_store.get_node("multi")
        ref_a = next(r for r in node.source_refs if r.event_id == "e_a")
        ref_b = next(r for r in node.source_refs if r.event_id == "e_b")
        assert ref_a.valid is False
        assert ref_b.valid is True


class TestGraphStoreReconcile:
    """启动自愈 reconcile：悬空引用 / hash 漂移 → invalid，一致源证保持 valid"""

    @pytest.mark.asyncio
    async def test_sync_source_ref_hash_updates_matching_refs(self, graph_store: GraphStore):
        from tests.factories import make_node
        await make_node(graph_store, "n1", "T", "c", event_id="e1")
        await make_node(graph_store, "n2", "T2", "c2", event_id="e2")
        graph_store.sync_source_ref_hash("e1", "newhash")
        assert graph_store.get_node("n1").source_refs[0].hash == "newhash"
        assert graph_store.get_node("n2").source_refs[0].hash != "newhash"

    @pytest.mark.asyncio
    async def test_reconcile_invalidates_dangling_ref(self, graph_store: GraphStore, event_store):
        graph_store.add_node(GraphNode(
            node_id="dangling", title="D", content="c",
            node_type=NodeType.interaction,
            source_refs=[SourceRef(event_id="ghost", valid=True, hash="h")],
            confidence=0.5, metadata=NodeMetadata(evidence_quote="c"),
        ))
        assert await graph_store.reconcile(event_store) == 1
        assert graph_store.get_node("dangling").source_refs[0].valid is False

    @pytest.mark.asyncio
    async def test_reconcile_invalidates_hash_mismatch(self, graph_store: GraphStore, event_store):
        eid, _ = await event_store.insert("actual content")
        graph_store.add_node(GraphNode(
            node_id="stale", title="S", content="c",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id=eid, valid=True, hash="wronghash")],
            confidence=0.5, metadata=NodeMetadata(evidence_quote="c"),
        ))
        assert await graph_store.reconcile(event_store) == 1
        assert graph_store.get_node("stale").source_refs[0].valid is False

    @pytest.mark.asyncio
    async def test_reconcile_keeps_matching_ref_valid(self, graph_store: GraphStore, event_store):
        from core.event_store import _content_hash
        eid, _ = await event_store.insert("actual content")
        graph_store.add_node(GraphNode(
            node_id="ok", title="O", content="c",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id=eid, valid=True, hash=_content_hash("actual content"))],
            confidence=0.5, metadata=NodeMetadata(evidence_quote="c"),
        ))
        assert await graph_store.reconcile(event_store) == 0
        assert graph_store.get_node("ok").source_refs[0].valid is True
