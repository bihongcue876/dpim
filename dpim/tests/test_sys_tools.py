"""Sys 工具测试：系统去重预检 + 存图写入（merged_into / 自动改道合并 / 正常新建）+ 查图召回"""

import pytest

from controller.tools import tool_apply_to_store, tool_graph_query
from controller.tools.sys_tools import (
    find_redundant_node,
    run_maintenance_local_checks,
    scan_maintenance_candidates,
    tool_apply_maintenance,
)
from core.models import (
    GraphBuildOutput,
    GraphNode,
    NodeCreate,
    NodeMetadata,
    NodeType,
    SourceRef,
)


def _node(nid, title, content, node_type=NodeType.data, confidence=0.8):
    return GraphNode(
        node_id=nid, title=title, content=content, node_type=node_type,
        source_refs=[SourceRef(event_id="e0", valid=True, hash="h")],
        confidence=confidence, metadata=NodeMetadata(evidence_quote=title),
    )


def _proposal(nc_title, nc_content, merged_into=None):
    return GraphBuildOutput(
        new_nodes=[
            NodeCreate(
                title=nc_title, content=nc_content,
                node_type=NodeType.data, confidence=0.9,
                evidence_quote=nc_content[:20],
            )
        ],
        new_edges=[],
        merged_into=merged_into,
    )


def _make_edge(source, target, relation):
    """测试辅助：构造一条边创建请求。"""
    from core.models import EdgeCreate
    return EdgeCreate(
        source=source, target=target, relation=relation,
        evidence_event_id="e0",
    )


class TestFindRedundantNode:
    """系统去重预检：词重叠 Jaccard ≥ 阈值（0.85）且同类型 → 命中"""

    def test_identical_content_same_type(self):
        nc = NodeCreate(
            title="Python异步编程", content="Python异步编程的实现方式",
            node_type=NodeType.data, confidence=0.9, evidence_quote="x",
        )
        candidates = [_node("n1", "Python异步编程", "Python异步编程的实现方式")]
        assert find_redundant_node(None, nc, candidates) == "n1"

    def test_low_overlap_returns_none(self):
        nc = NodeCreate(
            title="Python异步", content="协程与事件循环",
            node_type=NodeType.data, confidence=0.9, evidence_quote="x",
        )
        candidates = [_node("n1", "图数据库", "知识图谱存储")]
        assert find_redundant_node(None, nc, candidates) is None

    def test_different_type_not_merged(self):
        nc = NodeCreate(
            title="Python异步编程", content="Python异步编程的实现方式",
            node_type=NodeType.data, confidence=0.9, evidence_quote="x",
        )
        candidates = [
            _node("n1", "Python异步编程", "Python异步编程的实现方式",
                  node_type=NodeType.interaction),
        ]
        assert find_redundant_node(None, nc, candidates) is None

    def test_empty_candidates(self):
        nc = NodeCreate(
            title="T", content="c", node_type=NodeType.data,
            confidence=0.9, evidence_quote="x",
        )
        assert find_redundant_node(None, nc, []) is None


class TestApplyToStoreMerge:
    """存图写入：merged_into 不重复新建 / 去重自动改道 / 正常新建"""

    @pytest.mark.asyncio
    async def test_merged_into_no_new_nodes(self, db, event_store, graph_store):
        """Gr 显式 merged_into：内容并入已有节点，不新建（修复「既合并又重复新建」）。"""
        from tests.factories import make_event
        eid = await make_event(event_store, "Python异步编程的实现方式")
        graph_store.add_node(_node("existing", "Python异步编程", "旧内容"))
        proposal = _proposal("Python异步编程", "新内容", merged_into="existing")
        created = await tool_apply_to_store(event_store, graph_store, proposal, eid)
        assert created == ["existing"]
        assert graph_store.total_nodes() == 1  # 不新建
        node = graph_store.get_node("existing")
        assert "新内容" in node.content
        assert {sr.event_id for sr in node.source_refs} == {"e0", eid}
        # 反向索引：删除 eid 时 existing 的源证会失效（保护链路完整）
        assert "existing" in graph_store.get_nodes_for_event(eid)
        ev = await event_store.get(eid)
        assert ev["status"] == "linked"
        assert ev["graph_refs"] == ["existing"]

    @pytest.mark.asyncio
    async def test_auto_reroute_merge_on_redundant(self, db, event_store, graph_store):
        """新节点与 similar 高度重合 → 自动改道合并，不新建（防冗余）。"""
        from tests.factories import make_event
        eid = await make_event(event_store, "Python异步编程的实现方式")
        similar = [_node("n_dup", "Python异步编程", "Python异步编程的实现方式")]
        graph_store.add_node(similar[0])
        proposal = _proposal("Python异步编程", "Python异步编程的实现方式")
        created = await tool_apply_to_store(
            event_store, graph_store, proposal, eid, similar_nodes=similar,
        )
        assert created == ["n_dup"]  # 改道合并
        assert graph_store.total_nodes() == 1
        node = graph_store.get_node("n_dup")
        assert {sr.event_id for sr in node.source_refs} == {"e0", eid}

    @pytest.mark.asyncio
    async def test_normal_create_unchanged(self, db, event_store, graph_store):
        """无重合候选：正常新建，行为与旧版一致。"""
        from tests.factories import make_event
        eid = await make_event(event_store, "全新话题内容")
        proposal = _proposal("新话题", "全新内容")
        created = await tool_apply_to_store(event_store, graph_store, proposal, eid)
        assert len(created) == 1
        assert graph_store.get_node(created[0]) is not None
        assert graph_store.total_nodes() == 1

    @pytest.mark.asyncio
    async def test_edges_resolve_after_merge(self, db, event_store, graph_store):
        """改道合并后 new_edges 引用新节点 title 能正确落到合并目标节点。"""
        from tests.factories import make_event
        eid = await make_event(event_store, "Python异步编程")
        similar = [_node("n_dup", "Python异步编程", "Python异步编程的实现方式")]
        graph_store.add_node(similar[0])
        proposal = GraphBuildOutput(
            new_nodes=[
                NodeCreate(title="Python异步编程", content="Python异步编程的实现方式",
                           node_type=NodeType.data, confidence=0.9, evidence_quote="x"),
                NodeCreate(title="事件循环", content="事件循环机制",
                           node_type=NodeType.data, confidence=0.8, evidence_quote="y"),
            ],
            new_edges=[
                _make_edge("Python异步编程", "事件循环", "subtopic_of"),
            ],
            merged_into=None,
        )
        created = await tool_apply_to_store(
            event_store, graph_store, proposal, eid, similar_nodes=similar,
        )
        # 第一个节点改道合并到 n_dup，第二个正常新建
        assert created[0] == "n_dup"
        assert graph_store.total_nodes() == 2
        edges = graph_store.list_edges()
        assert len(edges) == 1
        assert edges[0]["source"] == "n_dup"  # title 解析到合并目标
        assert edges[0]["target"] == created[1]


class TestToolGraphQuery:
    @pytest.mark.asyncio
    async def test_word_overlap_supplement(self, graph_store):
        """FTS 未命中节点（不在 node_fts）但词重叠高 → 补充召回（Gr 能看到沾边节点）。"""
        from tests.factories import make_node
        await graph_store.upsert_node_fts("n_en", "Python Guide", "tutorial")
        await make_node(graph_store, "n_cn", "Python异步编程", "异步编程教程", event_id="e1")
        nodes = await tool_graph_query(graph_store, "Python 异步编程")
        ids = [n.node_id for n in nodes]
        assert "n_cn" in ids  # 词重叠补充召回

    @pytest.mark.asyncio
    async def test_fts_hit_still_returned(self, graph_store):
        from tests.factories import make_node
        await make_node(graph_store, "n1", "图数据库", "知识图谱存储", event_id="e1")
        nodes = await tool_graph_query(graph_store, "图数据库")
        assert any(n.node_id == "n1" for n in nodes)


# ── 图维护：扫描候选 / 本地审核 / 执行 ──


class TestScanMaintenanceCandidates:
    @pytest.mark.asyncio
    async def test_merge_candidates_found(self, graph_store):
        """同类型高度重合节点对 → 相似候选（内容更完整者作 target）。"""
        from tests.factories import make_node
        await make_node(
            graph_store, "a", "Python异步", "Python异步编程的实现方式详解", event_id="e1"
        )
        await make_node(
            graph_store, "b", "Python异步", "Python异步编程的实现方式", event_id="e2"
        )
        c = scan_maintenance_candidates(graph_store)
        pairs = c["merge_candidates"]
        assert len(pairs) >= 1
        assert pairs[0]["target_id"] == "a"  # 内容更完整者作 target

    @pytest.mark.asyncio
    async def test_different_type_not_candidate(self, graph_store):
        from tests.factories import make_node
        await make_node(graph_store, "a", "Python异步", "Python异步编程的实现方式",
                        event_id="e1", node_type=NodeType.data)
        await make_node(graph_store, "b", "Python异步", "Python异步编程的实现方式",
                        event_id="e2", node_type=NodeType.interaction)
        c = scan_maintenance_candidates(graph_store)
        assert c["merge_candidates"] == []

    @pytest.mark.asyncio
    async def test_zombie_and_isolated_found(self, graph_store):
        from tests.factories import make_node
        # 僵尸：无有效源证（不传 event_id）
        await make_node(graph_store, "z1", "僵尸节点", "无源内容")
        # 孤立低置信（有源证 → 不是僵尸，进 low_conf_isolated）
        await make_node(graph_store, "low", "孤立", "低置信内容", confidence=0.2, event_id="e9")
        c = scan_maintenance_candidates(graph_store)
        assert any(n["node_id"] == "z1" for n in c["zombie_nodes"])
        assert any(n["node_id"] == "low" for n in c["low_conf_isolated"])

    @pytest.mark.asyncio
    async def test_system_excluded_from_candidates(self, graph_store):
        from tests.factories import make_node
        await make_node(graph_store, "sys1", "系统节点", "无源内容",
                        node_type=NodeType.system)
        c = scan_maintenance_candidates(graph_store)
        assert c["zombie_nodes"] == []


class TestMaintenanceLocalChecks:
    @pytest.mark.asyncio
    async def test_system_delete_rejected(self, graph_store):
        from core.models import GraphMaintenancePlan, MaintenanceDelete
        from tests.factories import make_node
        await make_node(graph_store, "sys1", "系统", "内容", node_type=NodeType.system)
        plan = GraphMaintenancePlan(
            deletes=[MaintenanceDelete(node_id="sys1", reason="x")], confidence=0.9,
        )
        issues = run_maintenance_local_checks(graph_store, plan)
        assert issues and issues[0].type == "illegal_edge"

    @pytest.mark.asyncio
    async def test_data_with_valid_refs_delete_rejected(self, graph_store):
        from core.models import GraphMaintenancePlan, MaintenanceDelete
        from tests.factories import make_node
        await make_node(graph_store, "d1", "资料", "内容", event_id="e1")
        plan = GraphMaintenancePlan(
            deletes=[MaintenanceDelete(node_id="d1", reason="x")], confidence=0.9,
        )
        issues = run_maintenance_local_checks(graph_store, plan)
        assert len(issues) == 1

    @pytest.mark.asyncio
    async def test_cross_type_merge_rejected(self, graph_store):
        from core.models import GraphMaintenancePlan, MaintenanceMerge
        from tests.factories import make_node
        await make_node(graph_store, "d1", "同题", "内容", event_id="e1", node_type=NodeType.data)
        await make_node(graph_store, "i1", "同题", "内容", event_id="e2",
                        node_type=NodeType.interaction)
        plan = GraphMaintenancePlan(
            merges=[MaintenanceMerge(target_id="d1", source_ids=["i1"], reason="x")],
            confidence=0.9,
        )
        issues = run_maintenance_local_checks(graph_store, plan)
        assert len(issues) == 1

    @pytest.mark.asyncio
    async def test_legit_plan_passes(self, graph_store):
        from core.models import GraphMaintenancePlan, MaintenanceDelete
        from tests.factories import make_node
        await make_node(graph_store, "z1", "僵尸", "内容")
        plan = GraphMaintenancePlan(
            deletes=[MaintenanceDelete(node_id="z1", reason="无源证")], confidence=0.9,
        )
        assert run_maintenance_local_checks(graph_store, plan) == []


class TestApplyMaintenance:
    @pytest.mark.asyncio
    async def test_merge_execution(self, db, event_store, graph_store):
        """合并执行：target 吸收源证/内容/边，删除 source，FTS 同步。"""
        from core.models import GraphMaintenancePlan, MaintenanceMerge
        from tests.factories import make_edge, make_node
        await make_node(graph_store, "t", "主题", "内容A", event_id="e1")
        await make_node(graph_store, "s", "主题", "内容B", event_id="e2")
        await make_node(graph_store, "x", "相关", "内容X", event_id="e3")
        await make_edge(graph_store, "s", "x", event_id="e2")
        plan = GraphMaintenancePlan(
            merges=[MaintenanceMerge(target_id="t", source_ids=["s"], reason="重合")],
            confidence=0.9,
        )
        stats = await tool_apply_maintenance(event_store, graph_store, plan)
        assert stats["merged"][0]["sources"] == ["s"]
        assert graph_store.get_node("s") is None
        t = graph_store.get_node("t")
        assert {sr.event_id for sr in t.source_refs} == {"e1", "e2"}  # 源证并集
        assert "内容B" in t.content  # 内容合并
        # 边迁移：s→x 变为 t→x
        assert graph_store.get_edge("t", "x") is not None
        assert graph_store.get_edge("s", "x") is None
        # FTS：source 不可检索，target 可检索
        r = await graph_store.search_node_fts("内容B")
        assert any(x["node_id"] == "t" for x in r)

    @pytest.mark.asyncio
    async def test_delete_protection_guard(self, db, event_store, graph_store):
        """执行层兜底：data 有源证跳过删除；interaction 无源证可删。"""
        from core.models import GraphMaintenancePlan, MaintenanceDelete
        from tests.factories import make_node
        await make_node(graph_store, "d1", "资料", "内容", event_id="e1")  # data 有源证
        await make_node(graph_store, "i1", "对话", "内容", event_id="e2",
                        node_type=NodeType.interaction)
        graph_store.invalidate_source_ref("e2")
        plan = GraphMaintenancePlan(
            deletes=[
                MaintenanceDelete(node_id="d1", reason="x"),
                MaintenanceDelete(node_id="i1", reason="无源证"),
            ],
            confidence=0.9,
        )
        stats = await tool_apply_maintenance(event_store, graph_store, plan)
        assert stats["deleted"] == ["i1"]  # d1 被保护跳过
        assert graph_store.get_node("d1") is not None
        assert graph_store.get_node("i1") is None

    @pytest.mark.asyncio
    async def test_update_type_rules(self, db, event_store, graph_store):
        """修改规则：interaction 覆盖；data 追加；system 跳过。"""
        from core.models import GraphMaintenancePlan, MaintenanceUpdate
        from tests.factories import make_node
        await make_node(graph_store, "i1", "对话", "旧内容", event_id="e1",
                        node_type=NodeType.interaction)
        await make_node(graph_store, "d1", "资料", "旧资料", event_id="e2")
        await make_node(graph_store, "s1", "系统", "系统内容", node_type=NodeType.system)
        plan = GraphMaintenancePlan(
            updates=[
                MaintenanceUpdate(node_id="i1", content="修正后内容", reason="过时"),
                MaintenanceUpdate(node_id="d1", content="追加资料", reason="补充"),
                MaintenanceUpdate(node_id="s1", content="hack", reason="x"),
            ],
            confidence=0.9,
        )
        stats = await tool_apply_maintenance(event_store, graph_store, plan)
        assert stats["updated"] == ["i1", "d1"]
        assert graph_store.get_node("i1").content == "修正后内容"  # interaction 覆盖
        assert "追加资料" in graph_store.get_node("d1").content  # data 追加
        assert graph_store.get_node("s1").content == "系统内容"  # system 未动

    @pytest.mark.asyncio
    async def test_edge_remove(self, db, event_store, graph_store):
        from core.models import GraphMaintenancePlan, MaintenanceEdgeRemove
        from tests.factories import make_edge, make_node
        await make_node(graph_store, "a", "A", "内容", event_id="e1")
        await make_node(graph_store, "b", "B", "内容", event_id="e2")
        await make_edge(graph_store, "a", "b", event_id="e1")
        plan = GraphMaintenancePlan(
            edge_removes=[MaintenanceEdgeRemove(source="a", target="b", reason="错误边")],
            confidence=0.9,
        )
        stats = await tool_apply_maintenance(event_store, graph_store, plan)
        assert stats["edges_removed"] == ["a→b"]
        assert graph_store.get_edge("a", "b") is None
