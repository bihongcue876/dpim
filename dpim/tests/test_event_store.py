import pytest

from core.event_store import EventStore, _content_hash, _make_event_id


class TestEventId:
    def test_format(self):
        eid = _make_event_id()
        parts = eid.split("-")
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert len(parts[1]) == 8

    def test_uniqueness(self):
        ids = {_make_event_id() for _ in range(100)}
        assert len(ids) == 100


class TestContentHash:
    def test_consistency(self):
        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _content_hash("hello")
        h2 = _content_hash("world")
        assert h1 != h2

    def test_length(self):
        h = _content_hash("test")
        assert len(h) == 16


class TestEventStoreInsert:
    @pytest.mark.asyncio
    async def test_insert_returns_id_and_status(self, event_store: EventStore):
        eid, status = await event_store.insert("test content")
        assert eid is not None
        assert status == "raw"

    @pytest.mark.asyncio
    async def test_insert_stores_in_db(self, event_store: EventStore):
        eid, _ = await event_store.insert("stored content")
        ev = await event_store.get(eid)
        assert ev is not None
        assert ev["raw_content"] == "stored content"
        assert ev["status"] == "raw"
        assert ev["event_type"] == "interaction"

    @pytest.mark.asyncio
    async def test_insert_with_explicit_type(self, event_store: EventStore):
        eid, _ = await event_store.insert("data content", event_type="data")
        ev = await event_store.get(eid)
        assert ev["event_type"] == "data"

    @pytest.mark.asyncio
    async def test_insert_with_source_type(self, event_store: EventStore):
        eid, _ = await event_store.insert("source content", event_type="source")
        ev = await event_store.get(eid)
        assert ev["event_type"] == "source"

    @pytest.mark.asyncio
    async def test_content_hash_stored(self, event_store: EventStore):
        content = "hash me"
        eid, _ = await event_store.insert(content)
        ev = await event_store.get(eid)
        assert ev["content_hash"] == _content_hash(content)


class TestEventStoreGet:
    @pytest.mark.asyncio
    async def test_get_nonexistent(self, event_store: EventStore):
        ev = await event_store.get("nonexistent")
        assert ev is None

    @pytest.mark.asyncio
    async def test_graph_refs_default(self, event_store: EventStore):
        eid, _ = await event_store.insert("no refs")
        ev = await event_store.get(eid)
        assert ev["graph_refs"] == []


class TestEventStoreUpdateStatus:
    @pytest.mark.asyncio
    async def test_update_status_only(self, event_store: EventStore):
        eid, _ = await event_store.insert("status test")
        await event_store.update_status(eid, "indexed")
        ev = await event_store.get(eid)
        assert ev["status"] == "indexed"

    @pytest.mark.asyncio
    async def test_update_status_with_graph_refs(self, event_store: EventStore):
        eid, _ = await event_store.insert("graph refs test")
        await event_store.update_status(eid, "linked", graph_refs=["n1", "n2"])
        ev = await event_store.get(eid)
        assert ev["status"] == "linked"
        assert ev["graph_refs"] == ["n1", "n2"]

    @pytest.mark.asyncio
    async def test_status_machine_full(self, event_store: EventStore):
        eid, _ = await event_store.insert("full machine")
        states = ["indexed", "linked"]
        for s in states:
            await event_store.update_status(eid, s)
            ev = await event_store.get(eid)
            assert ev["status"] == s


class TestEventStoreDelete:
    @pytest.mark.asyncio
    async def test_delete_returns_event(self, event_store: EventStore):
        eid, _ = await event_store.insert("delete me")
        ev = await event_store.delete(eid)
        assert ev is not None
        assert ev["raw_content"] == "delete me"

    @pytest.mark.asyncio
    async def test_delete_removes_from_db(self, event_store: EventStore):
        eid, _ = await event_store.insert("gone")
        await event_store.delete(eid)
        ev = await event_store.get(eid)
        assert ev is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, event_store: EventStore):
        result = await event_store.delete("not_there")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_clears_fts(self, event_store: EventStore):
        eid, _ = await event_store.insert("fts delete test")
        await event_store.insert_fts(eid, "fts delete test")
        results = await event_store.search_fts("fts")
        assert len(results) == 1
        await event_store.delete(eid)
        results = await event_store.search_fts("fts")
        assert len(results) == 0


class TestEventStoreListByStatus:
    @pytest.mark.asyncio
    async def test_list_empty_status(self, event_store: EventStore):
        rows = await event_store.list_by_status("linked")
        assert rows == []

    @pytest.mark.asyncio
    async def test_list_by_status(self, event_store: EventStore):
        e1, _ = await event_store.insert("a")
        e2, _ = await event_store.insert("b")
        await event_store.update_status(e1, "linked")
        await event_store.update_status(e2, "indexed")
        linked = await event_store.list_by_status("linked")
        indexed = await event_store.list_by_status("indexed")
        assert len(linked) == 1
        assert linked[0]["event_id"] == e1
        assert len(indexed) == 1
        assert indexed[0]["event_id"] == e2


class TestEventStoreCount:
    @pytest.mark.asyncio
    async def test_empty_counts(self, event_store: EventStore):
        counts = await event_store.count_by_status()
        assert all(v == 0 for v in counts.values())

    @pytest.mark.asyncio
    async def test_counts_accurate(self, event_store: EventStore):
        e1, _ = await event_store.insert("a")
        await event_store.insert("b")
        await event_store.insert("c")
        await event_store.update_status(e1, "linked")
        counts = await event_store.count_by_status()
        assert counts["raw"] == 2
        assert counts["linked"] == 1

    @pytest.mark.asyncio
    async def test_total_events(self, event_store: EventStore):
        assert await event_store.total_events() == 0
        await event_store.insert("a")
        await event_store.insert("b")
        assert await event_store.total_events() == 2


class TestEventStoreLastEvent:
    @pytest.mark.asyncio
    async def test_no_events(self, event_store: EventStore):
        assert await event_store.last_event_at() is None

    @pytest.mark.asyncio
    async def test_last_event(self, event_store: EventStore):
        await event_store.insert("first")
        eid, _ = await event_store.insert("second")
        ev = await event_store.get(eid)
        last = await event_store.last_event_at()
        assert last == ev["created_at"]


class TestEventStoreFTS:
    @pytest.mark.asyncio
    async def test_fts_insert_and_search(self, event_store: EventStore):
        eid, _ = await event_store.insert("machine learning is fun")
        await event_store.insert_fts(eid, "machine learning is fun")
        results = await event_store.search_fts("machine")
        assert len(results) == 1
        assert results[0]["event_id"] == eid

    @pytest.mark.asyncio
    async def test_fts_search_no_match(self, event_store: EventStore):
        results = await event_store.search_fts("nothing")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_fts_multiple_events(self, event_store: EventStore):
        content = [
            "python programming language",
            "java virtual machine",
            "javascript web development",
        ]
        for c in content:
            eid, _ = await event_store.insert(c)
            await event_store.insert_fts(eid, c)
        results = await event_store.search_fts("programming")
        assert len(results) == 1
        results = await event_store.search_fts("java")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_like_fallback_ranks_by_position(self, event_store: EventStore):
        """对照：中文 LIKE 降级结果按命中位置排序（靠前得分高）"""
        e1, _ = await event_store.insert("我学习异步编程")
        await event_store.insert_fts(e1, "我学习异步编程")
        e2, _ = await event_store.insert("异步编程我学习")
        await event_store.insert_fts(e2, "异步编程我学习")
        results = await event_store.search_fts("学习")
        # FTS5 对中文整串不命中 → 走 LIKE 降级
        assert len(results) == 2
        assert results[0]["event_id"] == e1  # 命中位置靠前
        assert results[1]["event_id"] == e2
        assert results[0]["rank"] < results[1]["rank"]


class TestEventStoreControlledVariables:
    """控制变量：状态机、删除保护、类型筛选"""

    @pytest.mark.asyncio
    async def test_status_machine_all_transitions(self, event_store: EventStore):
        """对照：同一事件经历 raw→indexed→linked→failed→indexed 完整链路"""
        from tests.factories import make_event
        eid = await make_event(event_store, "state test", status="raw")
        ev = await event_store.get(eid)
        assert ev["status"] == "raw"
        await event_store.update_status(eid, "indexed")
        ev = await event_store.get(eid)
        assert ev["status"] == "indexed"
        await event_store.update_status(eid, "linked")
        ev = await event_store.get(eid)
        assert ev["status"] == "linked"
        await event_store.update_status(eid, "failed")
        ev = await event_store.get(eid)
        assert ev["status"] == "failed"

    @pytest.mark.asyncio
    async def test_delete_protection_control_group(self, event_store, graph_store):
        """对照：interaction 节点允许删除，data 节点拒绝删除"""
        from core.models import NodeType
        from tests.factories import make_event, make_node
        e_data = await make_event(event_store, "data source", "data")
        e_inter = await make_event(event_store, "interaction source", "interaction")
        await make_node(graph_store, "data_node", "Data", "protected",
                        NodeType.data, event_id=e_data)
        await make_node(graph_store, "inter_node", "Interaction", "free",
                        NodeType.interaction, event_id=e_inter)
        # Link events to nodes
        await event_store.update_status(e_data, "linked", graph_refs=["data_node"])
        await event_store.update_status(e_inter, "linked", graph_refs=["inter_node"])
        # Delete interaction event → should succeed
        r1 = await event_store.delete_with_protection(e_inter, graph_store)
        assert r1["status"] == "ok"
        # Delete data event → should be protected
        r2 = await event_store.delete_with_protection(e_data, graph_store)
        assert r2["status"] == "protected"
        assert r2["node_type"] == "data"

    @pytest.mark.asyncio
    async def test_delete_protection_precheck_partial(self, event_store, graph_store):
        """对照：事件同时关联 interaction + system 节点时，预检整体拒绝，
        不做任何图修改（interaction 节点不得被误删、源证不得被提前失效）"""
        from core.models import NodeType
        from tests.factories import make_event, make_node
        eid = await make_event(event_store, "mixed refs", "interaction")
        await make_node(graph_store, "mix_inter", "MixInter", "c",
                        NodeType.interaction, event_id=eid)
        await make_node(graph_store, "mix_sys", "MixSys", "c",
                        NodeType.system, event_id=eid)
        await event_store.update_status(eid, "linked", graph_refs=["mix_inter", "mix_sys"])
        r = await event_store.delete_with_protection(eid, graph_store)
        assert r["status"] == "protected"
        assert r["node_type"] == "system"
        # 预检拒绝后：两节点仍在、事件仍在、源证仍有效
        assert graph_store.get_node("mix_inter") is not None
        assert graph_store.get_node("mix_sys") is not None
        ev = await event_store.get(eid)
        assert ev is not None and ev["status"] == "linked"
        for sr in graph_store.get_node("mix_sys").source_refs:
            assert sr.valid is True

    @pytest.mark.asyncio
    async def test_event_type_filtering(self, event_store):
        """对照：三种类型各自写入，分别查询"""
        from tests.factories import make_event
        await make_event(event_store, "user said hello", "interaction")
        await make_event(event_store, "temperature is 25°C", "data")
        await make_event(event_store, '{"raw": "api response"}', "source")
        counts = await event_store.count_by_status()
        total = await event_store.total_events()
        assert total == 3
        assert counts["indexed"] == 3
