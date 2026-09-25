"""链 T 测试（协议 v1.28 / v1.29）：

T0 修复：
- T0-1 图层损坏留档（双损坏/超限 → .corrupt-* 留档 + 空图启动）
- T0-2 合并护栏（content 20000 / source_refs 500 上限）
- T0-3 events_fts 启动自愈
- T0-4 失败原因落库（events.error）+ 旧库迁移
- T0-5 检索排除 skipped 事件

T1-T3 册化：
- RepoManager 登记/迁移/受管开关/活动库
- repos 端点 + ingest/query 库参数 + 联合检索融合去重锚定
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.database import Database
from core.graph_store import (
    MAX_GRAPH_BYTES,
    GraphStore,
    _quarantine_corrupt,
)
from core.repos import DEFAULT_REPO_ID, RepoManager
from interface import api

# ── T0-1 图层损坏留档 ──────────────────────────


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


class TestGraphQuarantine:
    @pytest.mark.asyncio
    async def test_dual_corrupt_quarantines_original(self, db, tmp_path):
        """主文件与备份双损坏：原件留档 .corrupt-*，以空图启动，不静默覆盖"""
        json_path = tmp_path / "graph.json"
        _write(json_path, "{corrupted")
        _write(tmp_path / "graph.json.bak", "{also broken")
        gs = GraphStore(db, json_path=str(json_path))
        await gs.load()
        assert gs.total_nodes() == 0
        quarantined = list(tmp_path.glob("graph.json.corrupt-*"))
        assert len(quarantined) == 1
        assert quarantined[0].read_text(encoding="utf-8") == "{corrupted"
        assert not json_path.exists()  # 原位置已让位，后续 save 不覆盖留档

    @pytest.mark.asyncio
    async def test_backup_restore_keeps_original(self, db, tmp_path):
        """仅主文件损坏、备份可读：从备份恢复，原件不动作（下次 save 正常覆盖）"""
        json_path = tmp_path / "graph.json"
        _write(json_path, "{corrupted")
        _write(tmp_path / "graph.json.bak", '{"nodes": {}, "edges": []}')
        gs = GraphStore(db, json_path=str(json_path))
        await gs.load()
        assert gs.total_nodes() == 0
        assert list(tmp_path.glob("graph.json.corrupt-*")) == []
        assert json_path.read_text(encoding="utf-8") == "{corrupted"

    @pytest.mark.asyncio
    async def test_oversized_quarantined(self, db, tmp_path, monkeypatch):
        """超体量上限：视为损坏走留档路径"""
        monkeypatch.setattr("core.graph_store.MAX_GRAPH_BYTES", 16)
        json_path = tmp_path / "graph.json"
        _write(json_path, '{"nodes": {"a": {"huge": 1}}}')
        gs = GraphStore(db, json_path=str(json_path))
        await gs.load()
        assert gs.total_nodes() == 0
        assert len(list(tmp_path.glob("graph.json.corrupt-*"))) == 1

    def test_quarantine_rename_failure_is_swallowed(self, tmp_path):
        """留档失败（如目标被占用）不抛异常，仅记日志——启动不因留档受阻"""
        json_path = tmp_path / "graph.json"
        _write(json_path, "x")
        # 目录里预放同名只读冲突不可移植；直接对不存在文件调用只验证不抛
        _quarantine_corrupt(tmp_path / "missing.json")

    def test_max_graph_bytes_constant(self):
        assert MAX_GRAPH_BYTES == 64 * 1024 * 1024


# ── T0-2 合并护栏 ──────────────────────────


class TestMergeCaps:
    @pytest.mark.asyncio
    async def test_merge_into_content_capped(self, db, graph_store):
        from core.models import GraphNode, NodeMetadata, NodeType

        target = GraphNode(
            node_id="t1", title="T", content="A" * 19_990,
            node_type=NodeType.data, source_refs=[], confidence=0.5,
            metadata=NodeMetadata(evidence_quote="A", tags=[]),
        )
        graph_store.add_node(target)
        graph_store.merge_into("t1", event_id="e1", content="B" * 5_000)
        assert len(graph_store.get_node("t1").content) <= 20_000

    @pytest.mark.asyncio
    async def test_merge_into_source_refs_capped(self, db, graph_store):
        from core.models import GraphNode, NodeMetadata, NodeType, SourceRef

        refs = [SourceRef(event_id=f"e{i}", valid=True, hash="h") for i in range(500)]
        target = GraphNode(
            node_id="t2", title="T", content="c",
            node_type=NodeType.data, source_refs=refs, confidence=0.5,
            metadata=NodeMetadata(evidence_quote="c", tags=[]),
        )
        graph_store.add_node(target)
        for i in range(500, 510):
            graph_store.merge_into("t2", event_id=f"e{i}", content_hash="h")
        assert len(graph_store.get_node("t2").source_refs) == 500
        # 保留最新：最早的 e0/e1 已被挤出，最新的 e509 在列
        kept = {sr.event_id for sr in graph_store.get_node("t2").source_refs}
        assert {"e0", "e1"} & kept == set()
        assert "e509" in kept

    @pytest.mark.asyncio
    async def test_merge_nodes_content_capped(self, db, graph_store):
        from core.models import GraphNode, NodeMetadata, NodeType

        target = GraphNode(
            node_id="m1", title="M", content="A" * 19_000,
            node_type=NodeType.data, source_refs=[], confidence=0.5,
            metadata=NodeMetadata(evidence_quote="A", tags=[]),
        )
        source = GraphNode(
            node_id="m2", title="M2", content="B" * 5_000,
            node_type=NodeType.data, source_refs=[], confidence=0.5,
            metadata=NodeMetadata(evidence_quote="B", tags=[]),
        )
        graph_store.add_node(target)
        graph_store.add_node(source)
        removed = graph_store.merge_nodes("m1", ["m2"])
        assert removed == ["m2"]
        assert len(graph_store.get_node("m1").content) <= 20_000


# ── T0-3 events_fts 自愈 ──────────────────────────


class TestFtsRebuild:
    @pytest.mark.asyncio
    async def test_rebuild_restores_missing_rows(self, event_store):
        """索引行丢失 → rebuild 以事件表为真源补齐（检索可见性由 LIKE 兜底保证，
        rebuild 修的是 FTS rank 质量与索引一致性——对齐 node_fts 链 F2 先例）"""
        eid, _ = await event_store.insert_event("Python performance notes", "data")
        await event_store.db.conn.execute("DELETE FROM events_fts")
        await event_store.db.conn.commit()
        cursor = await event_store.db.conn.execute("SELECT COUNT(*) FROM events_fts")
        assert (await cursor.fetchone())[0] == 0
        await event_store.rebuild_fts()
        cursor = await event_store.db.conn.execute("SELECT COUNT(*) FROM events_fts")
        assert (await cursor.fetchone())[0] == 1
        rows = await event_store.search_fts("Python")
        assert eid in {r["event_id"] for r in rows}


# ── T0-4 失败原因落库 + 迁移 ──────────────────────────


class TestErrorField:
    @pytest.mark.asyncio
    async def test_error_roundtrip_and_clear(self, event_store):
        eid, _ = await event_store.insert("some content", "data")
        await event_store.update_status(eid, "failed", error="RuntimeError: boom")
        rows, _total = await event_store.list_events(status="failed")
        assert rows[0]["error"] == "RuntimeError: boom"
        await event_store.update_status(eid, "indexed", error="")
        rows, _total = await event_store.list_events()
        assert rows[0]["error"] == ""

    @pytest.mark.asyncio
    async def test_error_truncated_to_500(self, event_store):
        eid, _ = await event_store.insert("content", "data")
        await event_store.update_status(eid, "failed", error="x" * 900)
        rows, _total = await event_store.list_events()
        assert len(rows[0]["error"]) == 500

    @pytest.mark.asyncio
    async def test_error_none_keeps_value(self, event_store):
        eid, _ = await event_store.insert("content", "data")
        await event_store.update_status(eid, "failed", error="boom")
        await event_store.update_status(eid, "failed")
        rows, _total = await event_store.list_events()
        assert rows[0]["error"] == "boom"

    @pytest.mark.asyncio
    async def test_legacy_db_migration_adds_error(self, tmp_path):
        """v1 旧库（无 error 列）连接后自动迁移到 v2"""
        db_path = tmp_path / "legacy.db"
        raw = sqlite3.connect(str(db_path))
        raw.executescript("""
            CREATE TABLE events (
                event_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                raw_content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'raw',
                graph_refs TEXT DEFAULT '[]'
            );
            INSERT INTO events(event_id, created_at, raw_content, content_hash, event_type, status)
            VALUES ('old-1', '2026-01-01', 'legacy row', 'h', 'data', 'linked');
            PRAGMA user_version = 1;
        """)
        raw.commit()
        raw.close()

        database = Database(str(db_path))
        await database.connect()
        try:
            cursor = await database.conn.execute(
                "SELECT event_id, error FROM events WHERE event_id = 'old-1'"
            )
            row = await cursor.fetchone()
            assert row["event_id"] == "old-1"
            assert row["error"] == ""
            cursor = await database.conn.execute("PRAGMA user_version")
            assert (await cursor.fetchone())[0] == 2
        finally:
            await database.close()


# ── T0-5 检索排除 skipped ──────────────────────────


class TestSkippedExcluded:
    @pytest.mark.asyncio
    async def test_fts_branch_excludes_skipped(self, event_store):
        keep, _ = await event_store.insert_event("kubernetes cluster setup", "data")
        skip, _ = await event_store.insert("kubernetes networking", "data")
        await event_store.update_status(skip, "skipped")
        rows = await event_store.search_fts("kubernetes")
        assert [r["event_id"] for r in rows] == [keep]

    @pytest.mark.asyncio
    async def test_like_branch_excludes_skipped(self, event_store):
        keep, _ = await event_store.insert_event("八段锦呼吸法要领", "data")
        skip, _ = await event_store.insert("八段锦进阶口诀", "data")
        await event_store.update_status(skip, "skipped")
        # 分支无关断言：中文查询无论走 FTS 还是 LIKE 降级，skipped 均不可见
        rows = await event_store.search_fts("八段锦")
        ids = {r["event_id"] for r in rows}
        assert keep in ids
        assert skip not in ids


# ── T1-T3 册化 ──────────────────────────


@pytest.fixture
def repo_client(db, event_store, graph_store, tmp_path, monkeypatch):
    """册化测试环境：默认库绑定 fixture 三件套，repos_root 指向 tmp_path。"""
    monkeypatch.setattr(settings, "memory_db_path", str(tmp_path / "memory.db"))
    monkeypatch.setattr(settings, "graph_json_path", str(tmp_path / "graph.json"))
    api.db = db
    api.event_store = event_store
    api.graph_store = graph_store
    mgr = RepoManager()
    mgr.bind_default(db, event_store, graph_store)
    api.repos = mgr
    client = TestClient(api.app)
    yield client, mgr, tmp_path
    api.repos = None


class TestRepoManager:
    @pytest.mark.asyncio
    async def test_initialize_writes_default_registry(self, repo_client):
        """首次 initialize：默认库（external）登记落盘（legacy 零移动迁移）"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        index = json.loads((tmp_path / "repos" / "index.json").read_text(encoding="utf-8"))
        assert [b["repo_id"] for b in index["repos"]] == [DEFAULT_REPO_ID]
        assert index["repos"][0]["root_kind"] == "external"
        assert index["active_repo_id"] == DEFAULT_REPO_ID

    @pytest.mark.asyncio
    async def test_corrupt_index_kept_not_overwritten(self, repo_client):
        """坏登记表：保留原件、仅默认库运行、不覆盖"""
        client, mgr, tmp_path = repo_client
        index_path = tmp_path / "repos" / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("{broken", encoding="utf-8")
        await mgr.initialize()
        assert index_path.read_text(encoding="utf-8") == "{broken"
        assert list(mgr.records) == [DEFAULT_REPO_ID]

    @pytest.mark.asyncio
    async def test_create_managed_repo_layout(self, repo_client):
        client, mgr, tmp_path = repo_client
        record = await mgr.create_repo("小说资料", group="文学")
        # 书库 = 文件夹：group_key 目录 + 库目录，两文件就位
        assert record.group_key.startswith("grp-")
        repo_dir = tmp_path / "repos" / record.group_key / record.repo_id
        assert (repo_dir / "memory.db").exists()
        assert (repo_dir / "graph.json").exists()
        names = [b["name"] for b in client.get("/repos").json()["repos"]]
        assert record.name in names
        assert "默认库" in names

    @pytest.mark.asyncio
    async def test_managed_toggle_unloads_without_deleting(self, repo_client):
        client, mgr, tmp_path = repo_client
        record = await mgr.create_repo("临时库")
        await mgr.update_repo(record.repo_id, managed=False)
        assert record.repo_id not in mgr.entries  # 已卸载
        import os as _os
        assert _os.path.exists(record.db_path)  # 文件保留
        # 休眠库不可解析
        assert mgr.resolve(record.repo_id) is None
        # 活动库休眠 → 回落默认库
        await mgr.update_repo(record.repo_id, managed=True)  # 重新受管（重新打开）
        assert mgr.resolve(record.repo_id) is not None
        await mgr.activate(record.repo_id)
        assert mgr.active_id == record.repo_id
        await mgr.update_repo(record.repo_id, managed=False)
        assert mgr.active_id == DEFAULT_REPO_ID

    @pytest.mark.asyncio
    async def test_external_registration_and_forbidden(self, repo_client, tmp_path):
        client, mgr, _ = repo_client
        # 合法 external：目录含两文件
        ext = tmp_path / "extlib"
        ext.mkdir()
        d = Database(str(ext / "memory.db"))
        await d.connect()
        await d.close()
        (ext / "graph.json").write_text('{"nodes": {}, "edges": []}', encoding="utf-8")
        record = await mgr.create_repo("外置库", root_kind="external", root=str(ext))
        assert record.db_path == str(ext / "memory.db")
        # 禁设：目录不存在 / 缺文件 / 重复登记
        with pytest.raises(ValueError):
            await mgr.create_repo("x", root_kind="external", root=str(tmp_path / "nope"))
        incomplete = tmp_path / "incomplete"
        incomplete.mkdir()
        (incomplete / "memory.db").write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            await mgr.create_repo("x", root_kind="external", root=str(incomplete))
        with pytest.raises(ValueError):
            await mgr.create_repo("x", root_kind="external", root=str(ext))

    @pytest.mark.asyncio
    async def test_delete_repo_keeps_files(self, repo_client):
        client, mgr, _ = repo_client
        record = await mgr.create_repo("待摘库")
        import os as _os
        db_path = record.db_path
        await mgr.delete_repo(record.repo_id)
        assert record.repo_id not in mgr.records
        assert _os.path.exists(db_path)  # 只摘登记，不删磁盘
        with pytest.raises(ValueError):
            await mgr.delete_repo(DEFAULT_REPO_ID)


class TestRepoEndpoints:
    def test_repos_list_and_detail(self, repo_client):
        client, mgr, _ = repo_client
        resp = client.get("/repos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_repo_id"] == DEFAULT_REPO_ID
        assert len(data["repos"]) == 1
        assert data["repos"][0]["active"] is True
        assert data["repos"][0]["total_events"] is not None

        detail = client.get(f"/repos/{DEFAULT_REPO_ID}")
        assert detail.status_code == 200
        assert "status_counts" in detail.json()

    def test_create_and_ingest_to_repo(self, repo_client):
        client, mgr, tmp_path = repo_client
        created = client.post("/repos", json={"name": "游戏册", "group": "娱乐"})
        assert created.status_code == 200
        repo_id = created.json()["repo_id"]
        # ingest 指定册
        resp = client.post("/ingest", json={
            "event_type": "data", "content": "Minecraft 红石机关教程", "repo_id": repo_id,
        })
        assert resp.status_code == 200
        entry = mgr.resolve(repo_id)
        # 事件落目标册，默认库不受影响
        import asyncio
        assert asyncio.get_event_loop().run_until_complete(
            entry.event_store.total_events()
        ) == 1
        # 未知册 → 404
        assert client.post("/ingest", json={
            "event_type": "data", "content": "x", "repo_id": "bk_missing",
        }).status_code == 404

    def test_managed_toggle_via_endpoint(self, repo_client):
        client, mgr, _ = repo_client
        repo_id = client.post("/repos", json={"name": "休眠库"}).json()["repo_id"]
        assert client.put(f"/repos/{repo_id}", json={"managed": False}).status_code == 200
        assert client.get("/events", params={"repo_id": repo_id}).status_code == 404
        # 休眠库不可激活
        assert client.post(f"/repos/{repo_id}/activate").status_code == 409
        # 默认库不可摘
        assert client.delete(f"/repos/{DEFAULT_REPO_ID}").status_code == 409

    def test_generate_requires_ai(self, repo_client):
        client, mgr, _ = repo_client
        repo_id = client.post("/repos", json={"name": "生成库"}).json()["repo_id"]
        # 降级态 → 409 明示拒绝
        assert client.post(f"/repos/{repo_id}/generate").status_code == 409


class TestJointSearch:
    @pytest.mark.asyncio
    async def test_fuse_dedup_and_anchoring(self, repo_client):
        client, mgr, tmp_path = repo_client
        b1 = await mgr.create_repo("库一")
        b2 = await mgr.create_repo("库二")
        same = "kubernetes 集群部署实践完整指南内容"
        for entry in (mgr.resolve(b1.repo_id), mgr.resolve(b2.repo_id)):
            await entry.event_store.insert_event(same, "data")
        resp = client.post("/query", json={"query": "kubernetes"})
        assert resp.status_code == 200
        data = resp.json()
        # 两册同内容 → 去重为一条，来源锚定含两库名
        matching = [r for r in data["results"] if "kubernetes" in r["snippet"]]
        assert len(matching) == 1
        hit = matching[0]
        assert set(hit["source_repos"]) == {"库一", "库二"}
        assert hit["repo_name"] in {"库一", "库二"}

    @pytest.mark.asyncio
    async def test_single_explicit_repo_scoped(self, repo_client):
        client, mgr, _ = repo_client
        b1 = await mgr.create_repo("独查册")
        entry = mgr.resolve(b1.repo_id)
        await entry.event_store.insert_event("quantum computing overview", "data")
        resp = client.post("/query", json={
            "query": "quantum", "repo_ids": [b1.repo_id],
        })
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["repo_id"] == b1.repo_id
        # 默认库（未受管变更）无此内容 → 仅默认库检索为空
        resp2 = client.post("/query", json={"query": "quantum", "repo_ids": [DEFAULT_REPO_ID]})
        assert all("quantum" not in r["snippet"] for r in resp2.json()["results"])

    @pytest.mark.asyncio
    async def test_unknown_repo_id_rejected(self, repo_client):
        client, mgr, _ = repo_client
        # 单册显式未知 → 404（与其他库端点一致）；联合列表含未知册 → 422
        assert client.post(
            "/query", json={"query": "x", "repo_ids": ["bk_ghost"]},
        ).status_code == 404
        assert client.post("/query", json={
            "query": "x", "repo_ids": ["bk_ghost", DEFAULT_REPO_ID],
        }).status_code == 422

    @pytest.mark.asyncio
    async def test_events_and_nodes_filter_by_repo(self, repo_client):
        client, mgr, _ = repo_client
        b1 = await mgr.create_repo("过滤库")
        entry = mgr.resolve(b1.repo_id)
        eid, _ = await entry.event_store.insert_event("被过滤库独占的内容", "data")
        # 默认库查不到该事件
        resp_default = client.get("/events")
        assert all(e["event_id"] != eid for e in resp_default.json()["items"])
        # 指定册查得到
        resp_repo = client.get("/events", params={"repo_id": b1.repo_id})
        assert any(e["event_id"] == eid for e in resp_repo.json()["items"])


class TestHealthRepos:
    def test_health_exposes_queue_and_active_repo(self, repo_client):
        client, mgr, _ = repo_client
        resp = client.get("/health")
        data = resp.json()
        assert data["active_repo_id"] == DEFAULT_REPO_ID
        assert data["queue_depth"] == 0
        assert data["worker_running"] is False  # TestClient 未触发 lifespan
