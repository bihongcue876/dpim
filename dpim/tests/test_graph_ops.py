"""图层操作日志（graph_ops）测试：差分记录、纯函数重放、故障路径恢复。

覆盖 `core/graph_ops.py` 与 `GraphStore` 的集成：

- 差分：`save()` 把「相对上次落盘」的变更写成 op；无变更不写
- 重放：`replay()` 纯函数语义（含 node_delete 连带删边、graph_clear）
- 恢复：`graph.json` 丢失后 `load()` 从 graph_ops 复原图层（「派生」名实相符）
"""

import json

import pytest

from core.database import SCHEMA_VERSION
from core.graph_ops import (
    EDGE_DELETE,
    EDGE_UPSERT,
    GRAPH_CLEAR,
    NODE_DELETE,
    NODE_UPSERT,
    compact_ops,
    count_ops,
    diff_ops,
    list_ops,
    load_all_ops,
    replay,
    snapshot_graph,
)
from core.graph_store import GRAPH_FORMAT_VERSION, GraphStore
from core.models import GraphEdge, GraphNode, NodeMetadata, NodeType, SourceRef


def _node(node_id: str, title: str = "要点", content: str = "内容") -> GraphNode:
    return GraphNode(
        node_id=node_id,
        title=title,
        content=content,
        node_type=NodeType.data,
        confidence=0.5,
        source_refs=[SourceRef(event_id="e1", valid=True, hash="h")],
        metadata=NodeMetadata(evidence_quote="内容"),
    )


def _edge(src: str, dst: str, relation: str = "关联") -> GraphEdge:
    return GraphEdge(source=src, target=dst, relation=relation, evidence_event_id="e1")


class TestDiffOps:
    def test_new_node_and_edge(self):
        nodes = {"n1": _node("n1").model_dump(), "n2": _node("n2").model_dump()}
        edges = {("n1", "n2"): _edge("n1", "n2").model_dump()}
        ops = diff_ops({}, {}, nodes, edges)
        kinds = [op["kind"] for op in ops]
        assert kinds.count(NODE_UPSERT) == 2
        assert kinds.count(EDGE_UPSERT) == 1

    def test_removed_node_emits_delete_with_original_data(self):
        """删除 op 必须带上被删节点原数据：重放只按 id 删，但审计/抢救要看删了什么
        （合并吸收的 source 节点就靠这里留痕）。"""
        prev = {"n1": _node("n1").model_dump()}
        ops = diff_ops(prev, {}, {}, {})
        assert [op["kind"] for op in ops] == [NODE_DELETE]
        assert ops[0]["node_id"] == "n1"
        assert ops[0]["node"]["title"] == "要点"

    def test_changed_node_emits_upsert(self):
        prev = {"n1": _node("n1", title="旧").model_dump()}
        now = {"n1": _node("n1", title="新").model_dump()}
        ops = diff_ops(prev, {}, now, {})
        assert [op["kind"] for op in ops] == [NODE_UPSERT]

    def test_no_change_emits_nothing(self):
        nodes = {"n1": _node("n1").model_dump()}
        edges = {("n1", "n2"): _edge("n1", "n2").model_dump()}
        assert diff_ops(nodes, edges, nodes, edges) == []

    def test_removed_edge_emits_edge_delete(self):
        """删除 op 必须带上被删边原数据（v1.42，与 node_delete 对称）：
        整图清空后，这份 op 是边细节（relation / evidence_event_id）的唯一来源。"""
        edges = {("n1", "n2"): _edge("n1", "n2").model_dump()}
        ops = diff_ops({}, edges, {}, {})
        assert ops == [{
            "kind": EDGE_DELETE,
            "source": "n1",
            "target": "n2",
            "edge": _edge("n1", "n2").model_dump(),
        }]
        assert ops[0]["edge"]["relation"] == "关联"
        assert ops[0]["edge"]["evidence_event_id"] == "e1"


class TestReplay:
    def test_replay_rebuilds_nodes_and_edges(self):
        ops = [
            {"kind": NODE_UPSERT, "node": _node("n1").model_dump()},
            {"kind": NODE_UPSERT, "node": _node("n2").model_dump()},
            {"kind": EDGE_UPSERT, "edge": _edge("n1", "n2").model_dump()},
        ]
        nodes, edges = replay(ops)
        assert set(nodes) == {"n1", "n2"}
        assert set(edges) == {("n1", "n2")}

    def test_node_delete_drops_incident_edges(self):
        """与 NetworkX remove_node 语义一致：删节点连带删其关联边。"""
        ops = [
            {"kind": NODE_UPSERT, "node": _node("n1").model_dump()},
            {"kind": NODE_UPSERT, "node": _node("n2").model_dump()},
            {"kind": EDGE_UPSERT, "edge": _edge("n1", "n2").model_dump()},
            {"kind": NODE_DELETE, "node_id": "n1"},
        ]
        nodes, edges = replay(ops)
        assert set(nodes) == {"n2"}
        assert edges == {}

    def test_graph_clear(self):
        ops = [
            {"kind": NODE_UPSERT, "node": _node("n1").model_dump()},
            {"kind": GRAPH_CLEAR},
            {"kind": NODE_UPSERT, "node": _node("n9").model_dump()},
        ]
        nodes, _ = replay(ops)
        assert set(nodes) == {"n9"}

    def test_empty_ops(self):
        assert replay([]) == ({}, {})


class TestRecording:
    @pytest.mark.asyncio
    async def test_save_records_diff_once(self, db, tmp_path):
        gs = GraphStore(db, json_path=str(tmp_path / "g.json"))
        await gs.load()
        gs.add_node(_node("n1"))
        await gs.save()
        assert await count_ops(db.conn) == 1  # 只记新增节点
        await gs.save()  # 无变更 → 不再记录
        assert await count_ops(db.conn) == 1

    @pytest.mark.asyncio
    async def test_op_reason_attached_and_cleared(self, db, tmp_path):
        gs = GraphStore(db, json_path=str(tmp_path / "g.json"))
        await gs.load()
        gs.set_op_reason("维护计划: merges=1")
        gs.add_node(_node("n1"))
        await gs.save()
        ops = await list_ops(db.conn)
        assert ops[0]["reason"] == "维护计划: merges=1"
        gs.add_node(_node("n2"))
        await gs.save()
        ops = await list_ops(db.conn)
        assert ops[-1]["reason"] == ""  # 标签用后清空，不会粘到下一批

    @pytest.mark.asyncio
    async def test_replay_equals_live_graph(self, db, tmp_path):
        """差分日志必须能精确复原内存图（否则重放不可信）。"""
        gs = GraphStore(db, json_path=str(tmp_path / "g.json"))
        await gs.load()
        gs.add_node(_node("n1"))
        gs.add_node(_node("n2"))
        gs.add_edge(_edge("n1", "n2"))
        await gs.save()
        gs.update_node("n1", confidence=0.9)
        gs.remove_node("n2")
        gs.add_node(_node("n3"))
        await gs.save()

        from core.graph_ops import load_all_ops

        replayed_nodes, replayed_edges = replay(await load_all_ops(db.conn))
        live_nodes, live_edges = snapshot_graph(gs.graph)
        assert replayed_nodes == live_nodes
        assert replayed_edges == live_edges


class TestCompaction:
    """保留策略（v1.39）：graph_ops 压实——表有界，但**重放结果不变**。

    为什么不是直接截断：老 op 是「graph.json 丢失时的重放依据」，
    删了它重放只能还原后半段（恢复不完整、verify 恒红）。
    """

    @staticmethod
    async def _seed_churn(db, tmp_path, updates: int = 10) -> GraphStore:
        """3 节点 2 边 + 对同一节点反复改内容（纯 churn：每次落盘 1 条 op）。"""
        gs = GraphStore(db, json_path=str(tmp_path / "g.json"))
        await gs.load()
        for i in (1, 2, 3):
            gs.add_node(_node(f"n{i}"))
        gs.add_edge(_edge("n1", "n2"))
        gs.add_edge(_edge("n2", "n3"))
        await gs.save()  # 5 条 op
        for i in range(updates):
            gs.update_node("n1", content=f"内容-{i}")
            await gs.save()  # 每次 1 条 op（改的是同一节点 → 快照不随它变大）
        return gs

    @pytest.mark.asyncio
    async def test_compact_bounds_table_and_keeps_replay_equal(self, db, tmp_path):
        """**关键不变式**：压实后 `replay(全部 op)` 仍等于内存图（verify 口径不变）。"""
        gs = await self._seed_churn(db, tmp_path)
        before = await count_ops(db.conn)
        assert before == 15  # 5 + 10

        result = await compact_ops(db.conn, keep=4)

        assert result == {"before": 15, "after": 10, "removed": 11, "compacted": True}
        assert result["after"] == 4 + (1 + 3 + 2)  # 保留段 4 条 + 快照（clear + 3 节点 + 2 边）

        replayed_nodes, replayed_edges = replay(await load_all_ops(db.conn))
        live_nodes, live_edges = snapshot_graph(gs.graph)
        assert replayed_nodes == live_nodes
        assert replayed_edges == live_edges

        # 快照段在前、带来源标记；保留段原样保留（reason 不被压实覆盖）
        ops = await list_ops(db.conn)
        assert ops[0]["op_kind"] == GRAPH_CLEAR
        assert ops[0]["reason"] == "retention-compaction"
        assert len([o for o in ops if o["reason"] == "retention-compaction"]) == 6
        assert [o["op_kind"] for o in ops[-4:]] == [NODE_UPSERT] * 4

    @pytest.mark.asyncio
    async def test_compacted_log_still_recovers_missing_graph_json(self, db, tmp_path):
        """压实不损伤恢复能力：删掉 graph.json 后仍能从（压实过的）日志复原整图。"""
        path = tmp_path / "g.json"
        await self._seed_churn(db, tmp_path, updates=6)
        await compact_ops(db.conn, keep=3)

        path.unlink()
        fresh = GraphStore(db, json_path=str(path))
        await fresh.load()
        assert fresh.total_nodes() == 3
        assert fresh.total_edges() == 2
        assert fresh.get_node("n1").content == "内容-5"  # 最后一次修改也在

    @pytest.mark.asyncio
    async def test_keep_zero_disables_compaction(self, db, tmp_path):
        await self._seed_churn(db, tmp_path, updates=2)
        before = await count_ops(db.conn)

        result = await compact_ops(db.conn, keep=0)

        assert result["compacted"] is False and result["removed"] == 0
        assert await count_ops(db.conn) == before

    @pytest.mark.asyncio
    async def test_noop_when_snapshot_would_not_shrink_table(self, db, tmp_path):
        """纯追加（每轮新增节点+边）时快照与被替换的明细一样大 → 不动，避免越压越多。"""
        gs = GraphStore(db, json_path=str(tmp_path / "g.json"))
        await gs.load()
        for i in range(4):  # 1 + 2 + 2 + 2 = 7 条 op；快照 = 1 + 4 节点 + 3 边 = 8
            gs.add_node(_node(f"n{i}"))
            if i:
                gs.add_edge(_edge(f"n{i-1}", f"n{i}"))
            await gs.save()
        before = await count_ops(db.conn)
        assert before == 7

        result = await compact_ops(db.conn, keep=2)  # cut=5 < 快照 8 → 压不动

        assert result["compacted"] is False
        assert await count_ops(db.conn) == before

    @pytest.mark.asyncio
    async def test_below_keep_is_untouched(self, db, tmp_path):
        await self._seed_churn(db, tmp_path, updates=1)
        before = await count_ops(db.conn)  # 6 条 ≤ keep
        result = await compact_ops(db.conn, keep=50)
        assert result["compacted"] is False
        assert await count_ops(db.conn) == before


class TestRecoveryFromOps:
    @pytest.mark.asyncio
    async def test_missing_graph_json_recovered_from_ops(self, db, tmp_path):
        """核心承诺：graph.json 丢失后可从 graph_ops 重放复原图层。"""
        path = tmp_path / "g.json"
        gs = GraphStore(db, json_path=str(path))
        await gs.load()
        gs.add_node(_node("n1", title="红石机器"))
        gs.add_node(_node("n2", title="Minecraft"))
        gs.add_edge(_edge("n1", "n2", "属于"))
        await gs.save()
        assert gs.total_nodes() == 2

        path.unlink()  # 模拟图层文件丢失
        fresh = GraphStore(db, json_path=str(path))
        await fresh.load()
        assert fresh.total_nodes() == 2
        assert fresh.get_node("n1").title == "红石机器"
        assert fresh.total_edges() == 1
        assert fresh.dirty is True  # 重放结果待落盘

    @pytest.mark.asyncio
    async def test_empty_graph_json_is_not_replayed(self, db, tmp_path):
        """用户手动清空 graph.json 时不应复活旧节点（只有文件不可用才重放）。"""
        path = tmp_path / "g.json"
        gs = GraphStore(db, json_path=str(path))
        await gs.load()
        gs.add_node(_node("n1"))
        await gs.save()

        path.write_text(json.dumps({"nodes": {}, "edges": []}), encoding="utf-8")
        fresh = GraphStore(db, json_path=str(path))
        await fresh.load()
        assert fresh.total_nodes() == 0

    @pytest.mark.asyncio
    async def test_corrupt_graph_json_recovered_from_ops(self, db, tmp_path):
        path = tmp_path / "g.json"
        gs = GraphStore(db, json_path=str(path))
        await gs.load()
        gs.add_node(_node("n1"))
        await gs.save()
        bak = path.with_name("g.json.bak")
        if bak.exists():
            bak.unlink()  # 排除备份路径，强制走重放

        path.write_text("{ 不是合法 JSON", encoding="utf-8")
        fresh = GraphStore(db, json_path=str(path))
        await fresh.load()
        assert fresh.total_nodes() == 1


class TestFormatVersion:
    @pytest.mark.asyncio
    async def test_save_writes_format_version(self, db, tmp_path):
        path = tmp_path / "g.json"
        gs = GraphStore(db, json_path=str(path))
        await gs.load()
        gs.add_node(_node("n1"))
        await gs.save()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["format_version"] == GRAPH_FORMAT_VERSION

    @pytest.mark.asyncio
    async def test_newer_format_is_quarantined_and_not_replayed(self, db, tmp_path):
        path = tmp_path / "g.json"
        gs = GraphStore(db, json_path=str(path))
        await gs.load()
        gs.add_node(_node("n1"))
        await gs.save()

        path.write_text(
            json.dumps({"format_version": GRAPH_FORMAT_VERSION + 1, "nodes": {}, "edges": []}),
            encoding="utf-8",
        )
        fresh = GraphStore(db, json_path=str(path))
        await fresh.load()
        assert fresh.total_nodes() == 0  # 拒读且不用旧日志重放
        quarantined = list(tmp_path.glob("g.json.newer-v*"))
        assert len(quarantined) == 1


class TestSchemaVersion:
    @pytest.mark.asyncio
    async def test_graph_ops_table_created(self, db):
        cursor = await db.conn.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == SCHEMA_VERSION
        cursor = await db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='graph_ops'"
        )
        assert (await cursor.fetchone()) is not None
