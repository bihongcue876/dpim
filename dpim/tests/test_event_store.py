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


class TestLikeRank:
    """like_rank 相关性计分：标题优先、位置靠前加权、大小写不敏感"""

    def test_title_beats_content(self):
        from core.event_store import like_rank
        title_hit = like_rank("异步", "异步编程入门", "无相关内容")
        content_hit = like_rank("异步", "其他标题", "我学习异步编程")
        assert title_hit < content_hit  # rank 越小越相关

    def test_position_weights(self):
        from core.event_store import like_rank
        early = like_rank("学习", "", "我学习异步编程")
        late = like_rank("学习", "", "异步编程我学习")
        assert early < late

    def test_no_match_returns_zero(self):
        from core.event_store import like_rank
        assert like_rank("不存在", "标题", "内容") == 0.0

    def test_case_insensitive(self):
        from core.event_store import like_rank
        assert like_rank("PYTHON", "Python 编程", "c") == \
            like_rank("python", "Python 编程", "c")

    def test_empty_query(self):
        from core.event_store import like_rank
        assert like_rank("", "abc", "def") == 0.0


class TestSearchMultiToken:
    """多关键词 LIKE 降级：旧整串 LIKE 对多词查询基本全灭，现按词召回计分。"""

    @pytest.mark.asyncio
    async def test_multi_token_ranking(self, event_store: EventStore):
        from tests.factories import make_event

        eid_both = await make_event(event_store, "Python 异步编程教程", event_type="interaction")
        await make_event(event_store, "异步编程概念", event_type="interaction")
        # 查询含两个词；FTS5 中文不命中 → 降级多词 LIKE
        results = await event_store.search_fts("异步 教程")
        assert len(results) >= 2
        # 两词都命中的事件（"异步编程教程" 含 异步 + 教程）排最前
        assert results[0]["event_id"] == eid_both

    @pytest.mark.asyncio
    async def test_multi_token_no_overlap(self, event_store: EventStore):
        """多词查询中仅部分词命中也应召回（旧整串 LIKE 会漏掉）。"""
        from tests.factories import make_event

        eid = await make_event(event_store, "今天学习了Python基础语法", event_type="interaction")
        results = await event_store.search_fts("Python 网络爬虫")
        assert len(results) == 1
        assert results[0]["event_id"] == eid  # "Python" 命中即可召回


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

    @pytest.mark.asyncio
    async def test_fts_special_char_query_falls_back(self, event_store: EventStore):
        """查询串含 FTS5 特殊字符（语法错误）→ 降级 LIKE，不抛异常。

        切词后 "hello-world" 拆为 hello/world 两词，可召回 "hello world"
        （旧实现整串 LIKE 全灭，属改进）。
        """
        eid, _ = await event_store.insert("hello world")
        await event_store.insert_fts(eid, "hello world")
        results = await event_store.search_fts("hello-world")
        assert isinstance(results, list)  # 不抛异常
        assert len(results) == 1
        assert results[0]["event_id"] == eid


class TestEventStoreUpdateContent:
    """update_content 同步 FTS 索引：含 raw 状态事件尚无 FTS 行的场景"""

    @pytest.mark.asyncio
    async def test_update_content_creates_missing_fts_row(self, event_store: EventStore):
        """raw 状态事件（无 FTS 行）修订内容后必须能检索到新内容。

        旧实现 UPDATE events_fts 对无行事件是静默 no-op，修订内容永远搜不到。
        """
        eid, _ = await event_store.insert("original content about database")  # raw，未建 FTS
        ok = await event_store.update_content(eid, "revised content about quantum")
        assert ok is True
        results = await event_store.search_fts("quantum")
        assert len(results) == 1
        assert results[0]["event_id"] == eid

    @pytest.mark.asyncio
    async def test_update_content_replaces_existing_fts_row(self, event_store: EventStore):
        """已建 FTS 行的事件修订后：新内容可搜到，旧内容不再命中，且无重复行"""
        eid, _ = await event_store.insert_event("alpha beta gamma")
        ok = await event_store.update_content(eid, "delta epsilon zeta")
        assert ok is True
        assert len(await event_store.search_fts("epsilon")) == 1
        assert len(await event_store.search_fts("beta")) == 0
        # 无重复 FTS 行（先删后插）
        ev = await event_store.get(eid)
        assert ev["raw_content"] == "delta epsilon zeta"

    @pytest.mark.asyncio
    async def test_update_content_nonexistent_event(self, event_store: EventStore):
        assert await event_store.update_content("no-such-id", "x") is False

    @pytest.mark.asyncio
    async def test_update_content_syncs_source_ref_hash(self, event_store, graph_store):
        """修订事件内容后，引用该事件节点的 source_refs[].hash 同步为新 content_hash。"""
        from core.models import NodeType
        from tests.factories import make_node

        eid, _ = await event_store.insert("original content")
        await make_node(
            graph_store, "n1", "Node", "node content",
            NodeType.interaction, event_id=eid,
        )
        await event_store.update_status(eid, "linked", graph_refs=["n1"])
        ok = await event_store.update_content(eid, "revised content", graph_store)
        assert ok is True
        sr = graph_store.get_node("n1").source_refs[0]
        assert sr.hash == _content_hash("revised content")


class TestEventStoreGetMany:
    """get_many 批量取事件：去重、缺失跳过、空入参"""

    @pytest.mark.asyncio
    async def test_batch_with_missing_and_dedupe(self, event_store: EventStore):
        eid1, _ = await event_store.insert("alpha")
        eid2, _ = await event_store.insert("beta")
        got = await event_store.get_many([eid1, eid2, "missing", eid1])
        assert set(got) == {eid1, eid2}
        assert got[eid1]["raw_content"] == "alpha"
        assert got[eid2]["raw_content"] == "beta"

    @pytest.mark.asyncio
    async def test_empty_and_none(self, event_store: EventStore):
        assert await event_store.get_many([]) == {}
        assert await event_store.get_many(["no-such"]) == {}


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
    async def test_delete_protection_system_with_other_ref_allowed(
        self, event_store, graph_store
    ):
        """对照：system 节点还有其他有效源证 → 允许删除事件，节点保留且本事件 ref 失效"""
        from core.models import NodeType, SourceRef
        from tests.factories import make_event, make_node
        e1 = await make_event(event_store, "first ref", "interaction")
        e2 = await make_event(event_store, "second ref", "interaction")
        await make_node(graph_store, "sys_dual", "SysDual", "c",
                        NodeType.system, event_id=e1)
        # 给 system 节点追加第二个事件的源证
        node = graph_store.get_node("sys_dual")
        node.source_refs.append(SourceRef(event_id=e2, valid=True, hash="h"))
        graph_store.graph.nodes["sys_dual"]["data"] = node
        await event_store.update_status(e1, "linked", graph_refs=["sys_dual"])
        await event_store.update_status(e2, "linked", graph_refs=["sys_dual"])
        r = await event_store.delete_with_protection(e1, graph_store)
        assert r["status"] == "ok"
        # 事件已删、节点保留、e1 的 ref 失效而 e2 的仍有效
        assert await event_store.get(e1) is None
        node = graph_store.get_node("sys_dual")
        assert node is not None
        refs = {sr.event_id: sr.valid for sr in node.source_refs}
        assert refs[e1] is False
        assert refs[e2] is True

    @pytest.mark.asyncio
    async def test_delete_protection_all_interaction_cleared(
        self, event_store, graph_store
    ):
        """对照：多个 interaction 节点且无他证 → 删除事件后节点全部清空"""
        from core.models import NodeType
        from tests.factories import make_event, make_node
        eid = await make_event(event_store, "multi interaction", "interaction")
        for i in range(3):
            await make_node(graph_store, f"int_{i}", f"Int{i}", "c",
                            NodeType.interaction, event_id=eid)
        await event_store.update_status(
            eid, "linked", graph_refs=["int_0", "int_1", "int_2"])
        r = await event_store.delete_with_protection(eid, graph_store)
        assert r["status"] == "ok"
        for i in range(3):
            assert graph_store.get_node(f"int_{i}") is None
        assert graph_store.total_nodes() == 0

    @pytest.mark.asyncio
    async def test_delete_protection_no_refs(self, event_store, graph_store):
        """对照：事件无关联节点 → 直接删除"""
        from tests.factories import make_event
        eid = await make_event(event_store, "no refs")
        r = await event_store.delete_with_protection(eid, graph_store)
        assert r["status"] == "ok"
        assert await event_store.get(eid) is None

    @pytest.mark.asyncio
    async def test_delete_protection_event_not_found(self, event_store, graph_store):
        """对照：事件不存在 → not_found，不抛异常"""
        r = await event_store.delete_with_protection("ghost-event", graph_store)
        assert r["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_delete_protection_ref_to_missing_node_ok(
        self, event_store, graph_store
    ):
        """对照：graph_refs 指向已不存在的节点（脏引用）→ 跳过该引用正常删除"""
        from tests.factories import make_event
        eid = await make_event(event_store, "dirty ref")
        await event_store.update_status(eid, "linked", graph_refs=["vanished_node"])
        r = await event_store.delete_with_protection(eid, graph_store)
        assert r["status"] == "ok"

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
