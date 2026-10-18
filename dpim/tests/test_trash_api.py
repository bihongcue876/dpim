"""回收站端点测试（协议 v1.31）：`GET /trash`、`POST /trash/restore`。

覆盖：清单（内容摘要 title / 倒序 / 目录回报）、事件按**原 id** 恢复（FTS 重建、
留档移入 `trash/restored/`）、节点恢复（本体 + source_refs + 留档边尽力补回）、
冲突 409 / 缺失 404 / 非法 kind 422 的中文错误语义。

用真实文件库（留档要落盘到库同级的 `trash/`）。
"""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import GraphEdge, GraphNode, NodeMetadata, NodeType, SourceRef
from core.trash import archive_event, archive_node, prune_trash, trash_root
from interface import api, deps


def _node(node_id: str, title: str, event_id: str = "e1") -> GraphNode:
    return GraphNode(
        node_id=node_id,
        title=title,
        content=f"{title} 的正文内容",
        node_type=NodeType.data,
        confidence=0.6,
        source_refs=[SourceRef(event_id=event_id, valid=True, hash="h1")],
        metadata=NodeMetadata(evidence_quote=f"{title} 的正文内容"),
    )


@pytest.fixture
def trash_env(real_db, tmp_path):
    """真实文件库 + 独立 graph.json（与库同目录）；repos=None 走回落路径。"""
    es = EventStore(real_db)
    gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
    deps.db = real_db
    deps.event_store = es
    deps.graph_store = gs
    deps.repos = None
    yield TestClient(api.app), es, gs, tmp_path
    deps.repos = None


class TestTrashList:
    def test_empty_trash(self, trash_env):
        client, _es, _gs, tmp_path = trash_env
        resp = client.get("/trash")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert Path(data["dir"]).name == "trash"
        assert Path(data["dir"]).parent == tmp_path

    @pytest.mark.asyncio
    async def test_event_archive_listed_with_content_summary(self, trash_env):
        client, es, _gs, _tmp = trash_env
        eid, _ = await es.insert_event("红石机关教程全文", "data")
        assert client.delete(f"/events/{eid}").status_code == 200

        data = client.get("/trash").json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["kind"] == "event" and item["id"] == eid
        assert "红石机关教程" in item["title"]
        assert item["size"] > 0 and item["archived_at"]
        assert Path(item["path"]).is_file()

    def test_node_archive_listed_with_title(self, trash_env):
        client, _es, gs, _tmp = trash_env
        gs.add_node(_node("n1", "红石机器"))
        assert client.request(
            "DELETE", "/nodes/n1", json={"force": True}
        ).status_code == 200

        data = client.get("/trash").json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["kind"] == "node" and item["id"] == "n1"
        assert item["title"] == "红石机器"

    def test_items_sorted_newest_first(self, trash_env):
        client, _es, _gs, tmp_path = trash_env
        trash_dir = tmp_path / "trash" / "events"
        trash_dir.mkdir(parents=True, exist_ok=True)
        for eid, stamp in (("old", "2026-01-01T00:00:00+00:00"),
                           ("new", "2026-05-05T00:00:00+00:00")):
            (trash_dir / f"{eid}.json").write_text(
                json.dumps({
                    "archived_at": stamp, "kind": "events",
                    "data": {"event_id": eid, "raw_content": f"{eid} 内容"},
                }),
                encoding="utf-8",
            )
        items = client.get("/trash").json()["items"]
        assert [i["id"] for i in items] == ["new", "old"]


class TestTrashRestoreEvent:
    @pytest.mark.asyncio
    async def test_restore_keeps_original_id_and_moves_archive(self, trash_env):
        client, es, _gs, tmp_path = trash_env
        eid, _ = await es.insert_event("kubernetes 集群部署", "data")
        client.delete(f"/events/{eid}")
        assert await es.get(eid) is None

        resp = client.post("/trash/restore", json={"kind": "event", "id": eid})
        assert resp.status_code == 200
        assert "已恢复" in resp.json()["message"]
        restored = await es.get(eid)
        assert restored is not None and restored["raw_content"] == "kubernetes 集群部署"
        # FTS 重建：恢复后立即可检索
        assert eid in {r["event_id"] for r in await es.search_fts("kubernetes")}
        # 留档移入 trash/restored/（不删原文件）
        assert not (tmp_path / "trash" / "events" / f"{eid}.json").exists()
        assert (tmp_path / "trash" / "restored" / f"events-{eid}.json").is_file()
        assert client.get("/trash").json()["items"] == []

    @pytest.mark.asyncio
    async def test_restore_existing_event_conflicts(self, trash_env):
        client, es, _gs, _tmp = trash_env
        eid, _ = await es.insert_event("还在库里的事件", "data")
        archive_event(es.db.db_path, await es.get(eid))  # 留档存在但事件未删

        resp = client.post("/trash/restore", json={"kind": "event", "id": eid})
        assert resp.status_code == 409
        assert "已存在" in resp.json()["detail"]

    def test_restore_missing_archive_404(self, trash_env):
        client, _es, _gs, _tmp = trash_env
        resp = client.post("/trash/restore", json={"kind": "event", "id": "e_nope"})
        assert resp.status_code == 404
        assert "没有该事件的留档" in resp.json()["detail"]

    def test_restore_invalid_kind_422(self, trash_env):
        client, _es, _gs, _tmp = trash_env
        resp = client.post("/trash/restore", json={"kind": "book", "id": "x"})
        assert resp.status_code == 422


class TestTrashRestoreNode:
    def test_restore_node_body_refs_and_archived_edges(self, trash_env):
        client, _es, gs, tmp_path = trash_env
        gs.add_node(_node("a", "节点甲"))
        gs.add_node(_node("b", "节点乙", event_id="e2"))
        gs.add_edge(GraphEdge(
            source="a", target="b", relation="relates_to", evidence_event_id="e1",
        ))

        assert client.request(
            "DELETE", "/nodes/a", json={"force": True}
        ).status_code == 200
        assert gs.get_node("a") is None
        # 删除时留档了关联边（供恢复「能恢复多少恢复多少」）
        payload = json.loads((tmp_path / "trash" / "nodes" / "a.json").read_text(encoding="utf-8"))
        assert payload["edges"][0]["target"] == "b"

        resp = client.post("/trash/restore", json={"kind": "node", "id": "a"})
        assert resp.status_code == 200
        assert "补回关联边 1 条" in resp.json()["message"]
        node = gs.get_node("a")
        assert node is not None and node.title == "节点甲"
        assert [sr.event_id for sr in node.source_refs] == ["e1"]  # 源证保留
        assert gs.get_edge("a", "b") is not None
        assert not (tmp_path / "trash" / "nodes" / "a.json").exists()
        assert (tmp_path / "trash" / "restored" / "nodes-a.json").is_file()

    def test_restore_node_skips_edge_with_missing_endpoint(self, trash_env):
        """另一端已不在图中 → 不造悬空边（NetworkX 会造无 data 节点）。"""
        client, _es, gs, _tmp = trash_env
        gs.add_node(_node("a", "节点甲"))
        gs.add_node(_node("b", "节点乙", event_id="e2"))
        gs.add_edge(GraphEdge(
            source="a", target="b", relation="relates_to", evidence_event_id="e1",
        ))
        client.request("DELETE", "/nodes/a", json={"force": True})
        client.request("DELETE", "/nodes/b", json={"force": True})

        resp = client.post("/trash/restore", json={"kind": "node", "id": "a"})
        assert resp.status_code == 200
        assert "补回关联边 0 条" in resp.json()["message"]
        assert gs.get_edge("a", "b") is None

    def test_restore_existing_node_conflicts(self, trash_env):
        client, _es, gs, _tmp = trash_env
        gs.add_node(_node("n1", "红石机器"))
        archive_node(gs.json_path, _node("n1", "红石机器").model_dump())

        resp = client.post("/trash/restore", json={"kind": "node", "id": "n1"})
        assert resp.status_code == 409
        assert "已存在" in resp.json()["detail"]

    def test_restore_missing_node_archive_404(self, trash_env):
        client, _es, _gs, _tmp = trash_env
        resp = client.post("/trash/restore", json={"kind": "node", "id": "n_nope"})
        assert resp.status_code == 404
        assert "没有该节点的留档" in resp.json()["detail"]

    def test_restored_node_is_searchable(self, trash_env):
        """恢复的节点必须同步 node_fts，否则「恢复回来了却搜不到」。"""
        client, _es, gs, _tmp = trash_env
        gs.add_node(_node("n1", "八段锦呼吸法"))
        client.request("DELETE", "/nodes/n1", json={"force": True})
        assert client.post("/trash/restore", json={"kind": "node", "id": "n1"}).status_code == 200

        resp = client.get("/nodes", params={"query": "八段锦"})
        assert resp.status_code == 200
        assert any(item["node_id"] == "n1" for item in resp.json()["items"])

    def test_legacy_archive_without_edges_still_restores(self, trash_env):
        """v1.31 之前的留档没有 edges 字段：节点本体照常恢复，补边数为 0。"""
        client, _es, gs, tmp_path = trash_env
        trash_dir = tmp_path / "trash" / "nodes"
        trash_dir.mkdir(parents=True, exist_ok=True)
        (trash_dir / "legacy.json").write_text(
            json.dumps({
                "archived_at": "2026-01-01T00:00:00+00:00",
                "kind": "nodes",
                "data": _node("legacy", "旧留档节点").model_dump(),
            }),
            encoding="utf-8",
        )
        resp = client.post("/trash/restore", json={"kind": "node", "id": "legacy"})
        assert resp.status_code == 200
        assert "补回关联边 0 条" in resp.json()["message"]
        assert gs.get_node("legacy") is not None


class TestTrashRetention:
    """保留策略（v1.39）：`trash/` 按**年龄**清理。

    留档是已删数据的**最后一份副本**，清理即永久丢失——故只按年龄、默认 30 天、
    `0 = 永不清理`，且只动 `trash/{events,nodes,restored}` 里的 `.json`。
    """

    _NOW = 1_800_000_000.0  # 固定「现在」，避免依赖真实时钟

    @classmethod
    def _archive(cls, path: Path, *, age_days: float) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"archived_at": "2026-01-01T00:00:00+00:00", "kind": "events", "data": {}}),
            encoding="utf-8",
        )
        stamp = cls._NOW - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_prunes_only_expired_files(self, tmp_path):
        db_path = tmp_path / "memory.db"
        root = trash_root(db_path)
        old_event = self._archive(root / "events" / "e_old.json", age_days=40)
        old_node = self._archive(root / "nodes" / "n_old.json", age_days=31)
        old_restored = self._archive(root / "restored" / "nodes-n_old.json", age_days=99)
        fresh = self._archive(root / "events" / "e_new.json", age_days=2)

        result = prune_trash(db_path, 30, now=self._NOW)

        assert result["removed"] == 3
        assert result["kept"] == 1
        assert result["bytes"] > 0
        assert not old_event.exists()
        assert not old_node.exists()
        assert not old_restored.exists()  # restored/ 的痕迹同样按年龄清
        assert fresh.exists()

    def test_zero_days_never_prunes(self, tmp_path):
        """0 = 永不清理：留档是最后一份副本，默认不删（只有显式给天数才清）。"""
        db_path = tmp_path / "memory.db"
        ancient = self._archive(trash_root(db_path) / "events" / "e.json", age_days=3650)

        assert prune_trash(db_path, 0, now=self._NOW) == {"removed": 0, "kept": 0, "bytes": 0}
        assert ancient.exists()

    def test_ignores_non_json_and_unrelated_dirs(self, tmp_path):
        """只动三种留档目录里的 `.json`——别人的文件一律不碰。"""
        db_path = tmp_path / "memory.db"
        root = trash_root(db_path)
        note = root / "events" / "readme.txt"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("手写的说明", encoding="utf-8")
        other = root / "notes" / "foo.json"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("{}", encoding="utf-8")
        for item in (note, other):
            os.utime(item, (self._NOW - 400 * 86400,) * 2)

        result = prune_trash(db_path, 30, now=self._NOW)

        assert result["removed"] == 0
        assert note.exists() and other.exists()

    def test_missing_trash_dir_is_noop(self, tmp_path):
        assert prune_trash(tmp_path / "memory.db", 30) == {"removed": 0, "kept": 0, "bytes": 0}


class TestClearGraphArchive:
    """v1.42：`DELETE /graph` 先留档整图（可恢复）+ 撤销线层派生链接（不留谎报）。

    实测背景：此前清空只做 `clear_all()`，应用内**没有任何恢复路径**（删单个节点都有
    留档，一次删掉整图反而无处可恢复）；且线层事件仍是 `status=linked`、`graph_refs`
    指向已不存在的节点 → 概览台照旧显示「已入图 N」，`verify` 却全绿。
    """

    def _seed(self, gs, es):
        """两节点一边 + 一条 linked 事件（带 graph_refs）。"""
        gs.add_node(_node("n1", "红石机器"))
        gs.add_node(_node("n2", "红石电路"))
        gs.add_edge(GraphEdge(
            source="n1", target="n2", relation="related_to", evidence_event_id="e1",
        ))
        return gs

    @pytest.mark.asyncio
    async def test_clear_archives_graph_and_lists_it(self, trash_env):
        client, es, gs, _tmp = trash_env
        self._seed(gs, es)

        resp = client.request("DELETE", "/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["archived"] is True
        assert data["archive_id"].startswith("graph-")
        assert data["cleared_nodes"] == 2 and data["cleared_edges"] == 1
        assert gs.total_nodes() == 0 and gs.total_edges() == 0

        items = client.get("/trash").json()["items"]
        graph_items = [i for i in items if i["kind"] == "graph"]
        assert len(graph_items) == 1
        assert graph_items[0]["id"] == data["archive_id"]
        assert graph_items[0]["title"] == "整图留档：2 节点 / 1 边"
        assert Path(graph_items[0]["path"]).is_file()

    @pytest.mark.asyncio
    async def test_clear_revokes_derived_links(self, trash_env):
        """linked → indexed + 清 graph_refs：否则概览台谎报「已入图」，
        且 linked 不在补偿队列（raw/indexed）里 → 图永远长不回来。"""
        client, es, gs, _tmp = trash_env
        self._seed(gs, es)
        eid, _ = await es.insert_event("红石机器与电路", "data")
        await es.update_status(eid, "linked", graph_refs=["n1", "n2"])

        data = client.request("DELETE", "/graph").json()

        assert data["unlinked_events"] == 1 and data["relinked_events"] == 1
        ev = await es.get(eid)
        assert ev["status"] == "indexed"
        assert json.loads(ev["graph_refs"] or "[]") == []
        assert "回到「待处理」" in data["message"]

    @pytest.mark.asyncio
    async def test_restore_graph_merges_back(self, trash_env):
        """合并式恢复：缺的补回、已存在的跳过（不覆盖、不报 409）——清空后恢复即完整回填，
        图层已有内容时恢复也不会毁掉现有知识。"""
        client, es, gs, _tmp = trash_env
        self._seed(gs, es)
        archive_id = client.request("DELETE", "/graph").json()["archive_id"]
        # 清空后先手工放回一个同 id 节点：恢复必须跳过它、保留它的现内容
        gs.add_node(_node("n1", "手工放回的 n1"))

        resp = client.post("/trash/restore", json={"kind": "graph", "id": archive_id})
        assert resp.status_code == 200
        message = resp.json()["message"]
        assert "补回节点 1 个" in message and "跳过已存在 1 个" in message
        assert "补回边 1 条" in message and "合并式恢复，未覆盖现有图层" in message
        assert gs.total_nodes() == 2 and gs.total_edges() == 1
        assert gs.get_node("n1").title == "手工放回的 n1"      # 没被留档覆盖
        assert gs.get_edge("n1", "n2").relation == "related_to"
        # 留档移入 restored/（不删原件：保留「恢复过什么」的痕迹）
        moved = trash_root(es.db.db_path) / "restored" / f"graphs-{archive_id}.json"
        assert moved.is_file()
        assert not (trash_root(es.db.db_path) / "graphs" / f"{archive_id}.json").exists()

    @pytest.mark.asyncio
    async def test_restore_graph_skips_edges_with_missing_endpoints(self, trash_env):
        """留档里的边若端点没能回来（节点留档损坏等），不补该边——绝不造悬空边。"""
        client, _es, gs, tmp_path = trash_env
        archive_dir = tmp_path / "trash" / "graphs"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "graph-manual.json").write_text(json.dumps({
            "archived_at": "2026-10-17T00:00:00+00:00",
            "kind": "graphs",
            "data": {
                "nodes": [_node("n1", "只有一个端点").model_dump()],
                "edges": [{"source": "n1", "target": "missing", "relation": "r",
                           "evidence_event_id": "e1"}],
            },
        }, ensure_ascii=False), encoding="utf-8")

        resp = client.post("/trash/restore", json={"kind": "graph", "id": "graph-manual"})
        assert resp.status_code == 200
        assert "补回节点 1 个" in resp.json()["message"]
        assert "补回边 0 条" in resp.json()["message"]
        assert gs.total_nodes() == 1 and gs.total_edges() == 0

    @pytest.mark.asyncio
    async def test_restore_unknown_graph_archive_404(self, trash_env):
        client, _es, _gs, _tmp = trash_env
        resp = client.post("/trash/restore", json={"kind": "graph", "id": "graph-nope"})
        assert resp.status_code == 404
        assert "图层留档" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_clear_says_unrecoverable_when_archive_fails(
        self, trash_env, monkeypatch
    ):
        """留档失败仍照常清空，但**必须**在响应里明说不可恢复（不让用户以为能找回来）。"""
        client, es, gs, _tmp = trash_env
        self._seed(gs, es)
        monkeypatch.setattr(
            "interface.routers.nodes.archive_graph", lambda *a, **k: None
        )

        data = client.request("DELETE", "/graph").json()

        assert data["archived"] is False and data["archive_id"] == ""
        assert "留档失败，此操作不可恢复" in data["message"]
        assert gs.total_nodes() == 0
