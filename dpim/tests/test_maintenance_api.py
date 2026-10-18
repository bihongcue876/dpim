"""存储维护端点测试（P4）：备份 / 校验 / 操作日志 / WAL 检查点。

用真实文件库（备份依赖 `VACUUM INTO`，内存库不支持）。
"""

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.event_store import EventStore
from core.graph_ops import load_all_ops, replay, snapshot_graph
from core.graph_store import GraphStore
from core.models import GraphNode, NodeMetadata, NodeType, SourceRef
from core.trash import trash_root
from interface import api, deps
from interface.api import _run_retention_once


def _node(node_id: str) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        title="维护端点要点",
        content="内容",
        node_type=NodeType.data,
        confidence=0.5,
        source_refs=[SourceRef(event_id="e1", valid=True, hash="h")],
        metadata=NodeMetadata(evidence_quote="内容"),
    )


@pytest.fixture
async def maint_env(real_db, tmp_path):
    """真实文件库 + 独立 graph.json；api 全局指向它（repos=None 走回落路径）。"""
    es = EventStore(real_db)
    gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
    await gs.load()
    deps.db = real_db
    deps.event_store = es
    deps.graph_store = gs
    deps.repos = None
    yield TestClient(api.app), es, gs, real_db
    deps.repos = None


class TestBackupEndpoints:
    def test_backup_creates_directory_with_manifest(self, maint_env):
        client, _es, _gs, _db = maint_env
        resp = client.post("/maintenance/backup", params={"note": "接口测试"})
        assert resp.status_code == 200
        data = resp.json()
        assert Path(data["backup_dir"]).is_dir()
        assert data["manifest"]["note"] == "接口测试"

    def test_backup_then_list(self, maint_env):
        client, _es, _gs, _db = maint_env
        assert client.post("/maintenance/backup").status_code == 200
        resp = client.get("/maintenance/backups")
        assert resp.status_code == 200
        backups = resp.json()["backups"]
        assert len(backups) == 1
        assert "manifest" in backups[0]

    def test_backup_rejected_for_memory_db(self, db):
        deps.db = db
        deps.event_store = EventStore(db)
        deps.graph_store = GraphStore(db, json_path=":memory:")
        deps.repos = None
        resp = TestClient(api.app).post("/maintenance/backup")
        assert resp.status_code == 409


class TestVerifyEndpoint:
    def test_verify_returns_checks_and_sizes(self, maint_env):
        client, es, gs, db = maint_env
        resp = client.post("/maintenance/verify")
        assert resp.status_code == 200
        data = resp.json()
        names = {c["name"] for c in data["checks"]}
        assert {"sqlite_integrity", "events_fts_consistency", "ops_replay_matches_graph"} <= names
        assert data["sizes"]["db_bytes"] > 0


class TestOpsEndpoint:
    @pytest.mark.asyncio
    async def test_ops_exposes_audit_trail(self, maint_env):
        client, _es, gs, _db = maint_env
        gs.set_op_reason("接口测试改动")
        gs.add_node(_node("n1"))
        await gs.save()

        resp = client.get("/maintenance/ops")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["ops"][0]["reason"] == "接口测试改动"
        assert data["ops"][0]["op_kind"] == "node_upsert"
        assert data["ops"][0]["payload"]["node"]["node_id"] == "n1"

    def test_ops_empty_for_fresh_store(self, maint_env):
        client, _es, _gs, _db = maint_env
        data = client.get("/maintenance/ops").json()
        assert data["total"] == 0 and data["ops"] == []


class TestCheckpointEndpoint:
    def test_checkpoint_returns_frame_counts(self, maint_env):
        client, _es, _gs, _db = maint_env
        resp = client.post("/maintenance/checkpoint")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["busy"] == 0
        assert "wal_bytes" in data


class TestHealthStorage:
    def test_health_reports_capacity(self, maint_env):
        client, _es, _gs, _db = maint_env
        resp = client.get("/health")
        assert resp.status_code == 200
        storage = resp.json()["storage"]
        assert storage["db_bytes"] > 0
        assert "wal_bytes" in storage and "backups" in storage and "graph_ops" in storage


class TestTrashIntegration:
    """回收站与存储维护的交叉口径（v1.31）：留档计入 verify，恢复后不再计入。"""

    @pytest.mark.asyncio
    async def test_verify_counts_trash_then_restore_clears(self, maint_env):
        client, es, _gs, _db = maint_env
        eid, _ = await es.insert_event("待留档内容", "data")
        assert client.delete(f"/events/{eid}").status_code == 200

        sizes = client.post("/maintenance/verify").json()["sizes"]
        assert sizes["trash_items"] == 1
        assert client.get("/trash").json()["items"][0]["id"] == eid

        assert client.post(
            "/trash/restore", json={"kind": "event", "id": eid}
        ).status_code == 200
        # 恢复后留档移入 trash/restored/（不删原文件），不再计入待恢复项
        sizes = client.post("/maintenance/verify").json()["sizes"]
        assert sizes["trash_items"] == 0
        assert await es.get(eid) is not None


class TestRetentionWiring:
    """保留策略的运行接线（v1.39）：后台轮次真的压实 op 日志、清理过期留档。"""

    @pytest.mark.asyncio
    async def test_retention_once_compacts_ops_and_prunes_trash(
        self, real_db, tmp_path, monkeypatch
    ):
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        gs.add_node(_node("n1"))
        await gs.save()
        for i in range(5):  # 纯 churn：改同一节点，每次落盘 1 条 op
            gs.update_node("n1", content=f"c{i}")
            await gs.save()

        old = trash_root(real_db.db_path) / "events" / "e_old.json"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text("{}", encoding="utf-8")
        os.utime(old, ((time.time() - 40 * 86400),) * 2)

        entry = SimpleNamespace(repo_id="rp_test", db=real_db, graph_store=gs)
        monkeypatch.setattr(deps, "repos", SimpleNamespace(entries={"rp_test": entry}))
        monkeypatch.setattr(settings, "graph_ops_retention", 2)
        monkeypatch.setattr(settings, "trash_retention_days", 30)

        stats = await _run_retention_once()

        assert stats == {"repos": 1, "compacted": 1, "ops_removed": 4, "trash_removed": 1}
        assert not old.exists()
        # 压实后重放仍等于内存图（说明走的是 compact_ops，而不是简单截断）
        assert replay(await load_all_ops(real_db.conn)) == snapshot_graph(gs.graph)

    @pytest.mark.asyncio
    async def test_retention_once_without_repo_manager_is_noop(self, monkeypatch):
        """单库回落（无库管理器）：不动任何东西，也不报错。"""
        monkeypatch.setattr(deps, "repos", None)
        assert await _run_retention_once() == {
            "repos": 0, "compacted": 0, "ops_removed": 0, "trash_removed": 0,
        }
