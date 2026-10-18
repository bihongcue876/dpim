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

基层加固（2026-10-03，docs/数据资源接口设计20261003.md）：
- 坏索引只读锁存（原件永不覆盖）+ 登记表结构校验与上限
- group_key 独立生成（展示名不入路径）+ 同名分组复用
- 分组变更 = 目录迁移（失败回滚）+ external 重指向
- 禁设清单收严（数据根双向包含 / 符号链接）+ 建库失败回滚
- 可用性诊断（missing/root_error/load_error/last_reconcile_at）+ 显式 refresh
"""

import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.database import SCHEMA_VERSION, Database
from core.graph_store import (
    MAX_GRAPH_BYTES,
    GraphStore,
    _quarantine_corrupt,
)
from core.repos import (
    DEFAULT_REPO_ID,
    RepoIndexError,
    RepoManager,
    is_legacy_group_key,
)
from interface import api, deps

# ── T0-1 图层损坏留档 ──────────────────────────


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _make_external_dir(parent) -> Path:
    """造一个数据根之外、含 memory.db + graph.json 的 external 库目录。"""
    ext = Path(parent) / f"ext-{uuid.uuid4().hex[:8]}"
    ext.mkdir(parents=True, exist_ok=True)
    (ext / "graph.json").write_text('{"nodes": {}, "edges": []}', encoding="utf-8")
    (ext / "memory.db").write_bytes(b"")
    return ext


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
        """v1 旧库（无 error 列、无 graph_ops）连接后自动迁移到当前 schema 版本"""
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
            assert (await cursor.fetchone())[0] == SCHEMA_VERSION
            # v3：graph_ops 表随迁移建立（图层操作日志）
            cursor = await database.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='graph_ops'"
            )
            assert (await cursor.fetchone()) is not None
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
    deps.db = db
    deps.event_store = event_store
    deps.graph_store = graph_store
    mgr = RepoManager()
    mgr.bind_default(db, event_store, graph_store)
    deps.repos = mgr
    client = TestClient(api.app)
    yield client, mgr, tmp_path
    deps.repos = None


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
        assert record.group_key.startswith("grp_")
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
        # 合法 external：目录含两文件，且须在数据根之外（数据根 = tmp_path）
        ext = _make_external_dir(tmp_path.parent)
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


# ── P4 基层加固测试（补上一轮欠的覆盖）─────────────────────────────────────


def _index_path(tmp_path) -> Path:
    return tmp_path / "repos" / "index.json"


def _read_index(tmp_path) -> dict:
    return json.loads(_index_path(tmp_path).read_text(encoding="utf-8"))


def _write_index(tmp_path, payload: dict) -> None:
    _index_path(tmp_path).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


class TestRepoIndexHardening:
    @pytest.mark.asyncio
    async def test_corrupt_index_latches_read_only_and_keeps_original(self, repo_client):
        """坏索引只读锁存：绝不覆盖原件，也不阻断基础功能。"""
        _client, _mgr, tmp_path = repo_client
        _index_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        _write_index(tmp_path, {})  # 占位，随后写坏
        _index_path(tmp_path).write_text("{ 这不是合法 JSON", encoding="utf-8")

        fresh = RepoManager()
        await fresh.initialize()
        assert fresh.index_writable is False
        assert fresh.index_error
        assert _index_path(tmp_path).read_text(encoding="utf-8") == "{ 这不是合法 JSON"

    @pytest.mark.asyncio
    async def test_create_refused_while_latched(self, repo_client):
        _client, _mgr, tmp_path = repo_client
        _index_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        _index_path(tmp_path).write_text("{ 坏", encoding="utf-8")
        fresh = RepoManager()
        await fresh.initialize()
        with pytest.raises(RepoIndexError):
            await fresh.create_repo("新库")

    @pytest.mark.asyncio
    async def test_duplicate_repo_id_rejected(self, repo_client):
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        payload = _read_index(tmp_path)
        payload["repos"].append(dict(payload["repos"][0]))
        _write_index(tmp_path, payload)
        fresh = RepoManager()
        await fresh.initialize()
        assert fresh.index_writable is False
        assert "重复 repo_id" in fresh.index_error

    @pytest.mark.asyncio
    async def test_duplicate_path_pair_rejected(self, repo_client):
        """两条登记指向同一份文件 = 一库一 db 一 json 被破坏。"""
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        payload = _read_index(tmp_path)
        dup = dict(payload["repos"][0])
        dup["repo_id"] = "rp_other"
        payload["repos"].append(dup)
        _write_index(tmp_path, payload)
        fresh = RepoManager()
        await fresh.initialize()
        assert fresh.index_writable is False
        assert "同一份文件" in fresh.index_error

    @pytest.mark.asyncio
    async def test_missing_paths_rejected(self, repo_client):
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        payload = _read_index(tmp_path)
        payload["repos"][0]["db_path"] = ""
        _write_index(tmp_path, payload)
        fresh = RepoManager()
        await fresh.initialize()
        assert fresh.index_writable is False
        assert "db_path" in fresh.index_error

    @pytest.mark.asyncio
    async def test_bad_root_kind_rejected(self, repo_client):
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        payload = _read_index(tmp_path)
        payload["repos"][0]["root_kind"] = "weird"
        _write_index(tmp_path, payload)
        fresh = RepoManager()
        await fresh.initialize()
        assert fresh.index_writable is False
        assert "root_kind" in fresh.index_error


class TestExternalRootGuards:
    @pytest.mark.asyncio
    async def test_relative_root_rejected(self, repo_client):
        _client, mgr, _tmp = repo_client
        with pytest.raises(ValueError):
            await mgr.create_repo("外部库", root_kind="external", root="relative/dir")

    @pytest.mark.asyncio
    async def test_data_root_containment_rejected(self, repo_client):
        """数据根内的目录不许登记为 external（库文件会与登记表互相污染）。"""
        _client, mgr, tmp_path = repo_client
        with pytest.raises(ValueError) as exc:
            await mgr.create_repo("外部库", root_kind="external", root=str(tmp_path))
        assert "数据根" in str(exc.value)

    @pytest.mark.asyncio
    async def test_directory_containing_data_root_rejected(self, repo_client):
        _client, mgr, tmp_path = repo_client
        with pytest.raises(ValueError) as exc:
            await mgr.create_repo("外部库", root_kind="external", root=str(tmp_path.parent))
        assert "包含数据根" in str(exc.value)

    @pytest.mark.asyncio
    async def test_missing_files_rejected(self, repo_client):
        _client, mgr, tmp_path = repo_client
        empty = Path(tmp_path.parent) / f"empty-{uuid.uuid4().hex[:8]}"
        empty.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError) as exc:
            await mgr.create_repo("外部库", root_kind="external", root=str(empty))
        assert "memory.db" in str(exc.value) or "graph.json" in str(exc.value)

    @pytest.mark.asyncio
    async def test_valid_external_root_registers(self, repo_client):
        _client, mgr, tmp_path = repo_client
        outside = _make_external_dir(tmp_path.parent)
        record = await mgr.create_repo("外部库", root_kind="external", root=str(outside))
        assert record.root_kind == "external"
        assert record.repo_id in mgr.records


class TestGroupKeyDiscipline:
    @pytest.mark.asyncio
    async def test_group_key_is_uuid_based_not_name_derived(self, repo_client):
        """展示名不入路径：防注入、防改名冲突、防中文路径问题。"""
        _client, mgr, _tmp = repo_client
        record = await mgr.create_repo("库一", group="研究")
        assert record.group_key and record.group_key.startswith("grp_")
        assert "研究" not in record.group_key

    @pytest.mark.asyncio
    async def test_same_group_name_reuses_key(self, repo_client):
        _client, mgr, _tmp = repo_client
        first = await mgr.create_repo("库一", group="研究")
        second = await mgr.create_repo("库二", group="研究")
        assert first.group_key == second.group_key

    @pytest.mark.asyncio
    async def test_different_group_names_get_different_keys(self, repo_client):
        _client, mgr, _tmp = repo_client
        first = await mgr.create_repo("库一", group="研究")
        second = await mgr.create_repo("库二", group="工作")
        assert first.group_key != second.group_key

    def test_legacy_group_key_detected(self):
        assert is_legacy_group_key("grp-abc123") is True
        assert is_legacy_group_key("grp_abc123") is False
        assert is_legacy_group_key(None) is False


class TestRepoDiagnostics:
    @pytest.mark.asyncio
    async def test_diagnostics_reports_loaded_default(self, repo_client):
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        # 默认库两文件就位 → missing 应为空列表（诊断字段是「缺失文件名列表」）
        (tmp_path / "memory.db").write_bytes(b"")
        (tmp_path / "graph.json").write_text(
            '{"nodes": {}, "edges": []}', encoding="utf-8"
        )
        rows = await mgr.diagnostics()
        default = next(r for r in rows if r["repo_id"] == DEFAULT_REPO_ID)
        assert default["loaded"] is True
        assert default["missing"] == []
        assert "last_reconcile_at" in default and "load_error" in default

    @pytest.mark.asyncio
    async def test_diagnostics_flags_missing_files(self, repo_client):
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        record = mgr.records[DEFAULT_REPO_ID]
        record.db_path = str(tmp_path / "gone" / "memory.db")
        record.json_path = str(tmp_path / "gone" / "graph.json")
        rows = await mgr.diagnostics()
        default = next(r for r in rows if r["repo_id"] == DEFAULT_REPO_ID)
        assert "memory.db" in default["missing"]
        assert "graph.json" in default["missing"]


class TestRefreshRepo:
    @pytest.mark.asyncio
    async def test_refresh_returns_stats(self, repo_client):
        _client, mgr, _tmp = repo_client
        await mgr.initialize()
        info = await mgr.refresh_repo(DEFAULT_REPO_ID)
        assert info["repo_id"] == DEFAULT_REPO_ID
        assert {"events", "nodes", "edges"} <= set(info)

    @pytest.mark.asyncio
    async def test_refresh_unknown_repo_raises(self, repo_client):
        _client, mgr, _tmp = repo_client
        await mgr.initialize()
        with pytest.raises(KeyError):
            await mgr.refresh_repo("rp_nope")

    def test_refresh_endpoint_ok(self, repo_client):
        client, _mgr, _tmp = repo_client
        resp = client.post(f"/repos/{DEFAULT_REPO_ID}/refresh")
        assert resp.status_code == 200
        assert resp.json()["repo_id"] == DEFAULT_REPO_ID
        # v1.46：句首文案与对账变更数都必须真的下发（旧实现两者恒为空/0）
        assert resp.json()["message"]
        assert "reconcile_changed" in resp.json()

    def test_refresh_response_maps_changed_key(self):
        """v1.46 回归守卫：`refresh_repo()` 的键是 `changed`，响应模型要的是 `reconcile_changed`。

        旧实现直接 `RepoRefreshResponse(**info)`，而 Pydantic 对未知键是 `extra='ignore'`
        → 真值被**静默丢弃**、恒为 0：「刷新修复」永远报「源证对账变更 0 条」，
        存储体检页同一数字也恒 0（页面级单测按契约编造返回值，查不出这个）。
        """
        from core.models import RepoRefreshResponse

        info = {
            "repo_id": "rp_x", "name": "n", "events": 1, "nodes": 2, "edges": 3,
            "changed": 7, "last_reconcile_at": "2026-10-17T00:00:00+00:00",
        }
        assert RepoRefreshResponse(**info).reconcile_changed == 0  # 旧写法：真值被吞
        info["reconcile_changed"] = int(info.pop("changed", 0) or 0)  # router 里的映射
        assert RepoRefreshResponse(**info).reconcile_changed == 7

    def test_refresh_endpoint_unknown_repo_404(self, repo_client):
        client, _mgr, _tmp = repo_client
        assert client.post("/repos/rp_nope/refresh").status_code == 404


class TestCreateRollback:
    @pytest.mark.asyncio
    async def test_failed_open_rolls_back_registration_and_directory(
        self, repo_client, monkeypatch
    ):
        """建库先登记后建目录：开库失败必须摘登记 + 清目录，不留孤儿。"""
        _client, mgr, _tmp = repo_client
        await mgr.initialize()

        async def boom(self, record):
            raise RuntimeError("模拟开库失败")

        monkeypatch.setattr(RepoManager, "_open", boom)
        with pytest.raises(RuntimeError):
            await mgr.create_repo("会失败的库")
        assert all(record.name != "会失败的库" for record in mgr.records.values())
        assert not any(_tmp.joinpath("repos").glob("**/会失败的库"))


# ── v1.31：登记表重建 / 书目清除 / 外部库重指向 / 列表来源库归属 ──────────────


def _make_managed_dir(tmp_path, repo_dirname: str, group_key: str | None = None):
    """在受管库根下造一个「含 memory.db + graph.json」的库目录。"""
    base = tmp_path / "repos"
    if group_key:
        base = base / group_key
    target = base / repo_dirname
    target.mkdir(parents=True, exist_ok=True)
    (target / "memory.db").write_bytes(b"")
    (target / "graph.json").write_text('{"nodes": {}, "edges": []}', encoding="utf-8")
    return target


def _make_adopt_dir(tmp_path, *, with_db: bool, with_json: bool):
    """造一个数据根之外的「半损」目录：按需放入 memory.db / graph.json。"""
    target = Path(tmp_path.parent) / f"adopt-{uuid.uuid4().hex[:8]}"
    target.mkdir(parents=True, exist_ok=True)
    if with_db:
        (target / "memory.db").write_bytes(b"")
    if with_json:
        (target / "graph.json").write_text('{"nodes": {}, "edges": []}', encoding="utf-8")
    return target


class TestRepoRebuild:
    @pytest.mark.asyncio
    async def test_rebuild_clears_latch_and_rewrites_index(self, repo_client):
        """坏索引恢复：清掉只读锁存 → 重建登记表并落盘（原件被合法登记表替换）。"""
        _client, _mgr, tmp_path = repo_client
        _index_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        _index_path(tmp_path).write_text("{ 坏索引", encoding="utf-8")

        fresh = RepoManager()
        await fresh.initialize()
        assert fresh.index_writable is False  # 先锁存

        info = await fresh.rebuild_index()
        assert info["latched_before"] is True
        assert info["repos"] == 1  # 只有默认库
        assert fresh.index_writable is True and fresh.index_error == ""
        assert DEFAULT_REPO_ID in fresh.records
        payload = _read_index(tmp_path)  # 已是合法 JSON（原件不再被保留）
        assert payload["repos"][0]["repo_id"] == DEFAULT_REPO_ID

    @pytest.mark.asyncio
    async def test_rebuild_discovers_managed_dirs_on_disk(self, repo_client):
        """扫描受管库根：含 memory.db / graph.json 的目录重建为登记（不删任何数据）。"""
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        target = _make_managed_dir(tmp_path, "rp-scanned01", group_key="grp_abc")

        info = await mgr.rebuild_index()
        assert "rp-scanned01" in mgr.records
        record = mgr.records["rp-scanned01"]
        assert record.root_kind == "managed" and record.managed is True
        assert record.group_key == "grp_abc"
        assert record.db_path == str(target / "memory.db")
        assert info["repos"] == 2  # 默认库 + 扫描到的
        # 磁盘数据文件一个都不能少
        assert (target / "memory.db").is_file() and (target / "graph.json").is_file()

    @pytest.mark.asyncio
    async def test_rebuild_excludes_backup_copies(self, repo_client):
        """整库备份目录里的 memory.db 不是库：否则备份会被登记成书目。"""
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        target = _make_managed_dir(tmp_path, "rp-withbak")
        backup = target / "backups" / "20260101-000000"
        backup.mkdir(parents=True)
        (backup / "memory.db").write_bytes(b"")

        await mgr.rebuild_index()
        assert set(mgr.records) == {DEFAULT_REPO_ID, "rp-withbak"}

    @pytest.mark.asyncio
    async def test_rebuild_keeps_existing_external_root(self, repo_client):
        """外部库根不在扫描范围内，靠「旧登记提示 + 根仍存在」保留。"""
        _client, mgr, tmp_path = repo_client
        await mgr.initialize()
        outside = _make_external_dir(tmp_path.parent)
        record = await mgr.create_repo("外置保留库", root_kind="external", root=str(outside))

        await mgr.rebuild_index()
        assert record.repo_id in mgr.records
        assert mgr.records[record.repo_id].root_kind == "external"

    def test_rebuild_endpoint_reports_counts(self, repo_client):
        client, mgr, _tmp = repo_client
        resp = client.post("/repos/rebuild")
        assert resp.status_code == 200
        data = resp.json()
        assert data["latched_before"] is False
        assert data["repos"] == len(mgr.records)
        assert data["repos"] >= 1
        assert "登记表已重建" in data["message"]
        assert "未删除任何磁盘数据文件" in data["message"]


class TestRepoPurge:
    def test_purge_managed_repo_backs_up_then_deletes(self, repo_client):
        client, mgr, tmp_path = repo_client
        repo_id = client.post("/repos", json={"name": "待清除库"}).json()["repo_id"]
        record = mgr.records[repo_id]

        resp = client.post(f"/repos/{repo_id}/purge")
        assert resp.status_code == 200
        data = resp.json()
        # 先备份：备份目录含整库副本 + 清单
        backup = Path(data["backup_path"])
        assert backup.is_dir()
        assert (backup / "memory.db").is_file()
        assert (backup / "manifest.json").is_file()
        # 再删库文件
        assert not Path(record.db_path).exists()
        assert not Path(record.json_path).exists()
        assert not Path(str(record.db_path) + "-wal").exists()
        # 最后摘登记
        assert repo_id not in mgr.records
        assert all(r["repo_id"] != repo_id for r in _read_index(tmp_path)["repos"])

    def test_purge_default_repo_rejected_400(self, repo_client):
        client, _mgr, _tmp = repo_client
        resp = client.post(f"/repos/{DEFAULT_REPO_ID}/purge")
        assert resp.status_code == 400
        assert "默认库不可清除" in resp.json()["detail"]

    def test_purge_active_repo_rejected_409(self, repo_client):
        client, _mgr, _tmp = repo_client
        repo_id = client.post("/repos", json={"name": "活动中的库"}).json()["repo_id"]
        assert client.post(f"/repos/{repo_id}/activate").status_code == 200
        resp = client.post(f"/repos/{repo_id}/purge")
        assert resp.status_code == 409
        assert "活动库不可清除" in resp.json()["detail"]

    def test_purge_unknown_repo_404(self, repo_client):
        client, _mgr, _tmp = repo_client
        resp = client.post("/repos/rp_ghost/purge")
        assert resp.status_code == 404
        assert "库不存在" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_purge_dormant_managed_repo(self, repo_client):
        """休眠（未加载）的受管库也能清除：清除前临时开一次以便备份。"""
        client, mgr, _tmp = repo_client
        repo_id = client.post("/repos", json={"name": "休眠待清除库"}).json()["repo_id"]
        assert client.put(f"/repos/{repo_id}", json={"managed": False}).status_code == 200
        assert repo_id not in mgr.entries
        record = mgr.records[repo_id]

        resp = client.post(f"/repos/{repo_id}/purge")
        assert resp.status_code == 200
        assert Path(resp.json()["backup_path"]).is_dir()
        assert not Path(record.db_path).exists()
        assert repo_id not in mgr.records

    @pytest.mark.asyncio
    async def test_purge_external_keeps_files(self, repo_client):
        """外部库只摘登记：不删外部目录任何文件，也不在那里做备份。"""
        client, mgr, tmp_path = repo_client
        outside = _make_external_dir(tmp_path.parent)
        record = await mgr.create_repo("外部待摘库", root_kind="external", root=str(outside))

        resp = client.post(f"/repos/{record.repo_id}/purge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["backup_path"] == ""
        assert "未删除外部目录中的任何文件" in data["message"]
        assert (outside / "memory.db").is_file() and (outside / "graph.json").is_file()
        assert record.repo_id not in mgr.records


class TestExternalRootRepoint:
    @pytest.mark.asyncio
    async def test_repoint_external_repo_to_new_directory(self, repo_client):
        client, mgr, tmp_path = repo_client
        first = _make_external_dir(tmp_path.parent)
        second = _make_external_dir(tmp_path.parent)
        record = await mgr.create_repo("可重指向库", root_kind="external", root=str(first))

        resp = client.put(f"/repos/{record.repo_id}", json={"root": str(second)})
        assert resp.status_code == 200
        updated = mgr.records[record.repo_id]
        assert updated.db_path == str(second / "memory.db")
        assert updated.json_path == str(second / "graph.json")
        # 重指向后按新路径重新加载
        assert mgr.resolve(record.repo_id) is not None

    @pytest.mark.asyncio
    async def test_repoint_managed_repo_rejected_400(self, repo_client):
        client, mgr, _tmp = repo_client
        record = await mgr.create_repo("受管库")
        resp = client.put(f"/repos/{record.repo_id}", json={"root": str(_tmp / "repos")})
        assert resp.status_code == 400
        assert "受管库目录由系统管理" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_repoint_to_invalid_root_rejected(self, repo_client):
        client, mgr, tmp_path = repo_client
        first = _make_external_dir(tmp_path.parent)
        record = await mgr.create_repo("外部库", root_kind="external", root=str(first))
        resp = client.put(
            f"/repos/{record.repo_id}", json={"root": str(tmp_path / "not-there")}
        )
        assert resp.status_code == 422
        assert mgr.records[record.repo_id].db_path == str(first / "memory.db")


class TestListItemsCarryRepo:
    def test_events_list_items_carry_repo(self, repo_client):
        client, mgr, _tmp = repo_client
        repo_id = client.post("/repos", json={"name": "归属库"}).json()["repo_id"]
        client.post("/ingest", json={
            "content": "归属库的事件", "event_type": "data", "repo_id": repo_id,
        })

        scoped = client.get("/events", params={"repo_id": repo_id}).json()["items"]
        assert scoped and all(
            i["repo_id"] == repo_id and i["repo_name"] == "归属库" for i in scoped
        )
        default = client.get("/events").json()["items"]
        assert all(i["repo_id"] == DEFAULT_REPO_ID and i["repo_name"] == "默认库" for i in default)

    def test_events_query_branch_carries_repo(self, repo_client):
        """关键词检索分支（FTS 路径）同样带来源库归属。"""
        client, _mgr, _tmp = repo_client
        repo_id = client.post("/repos", json={"name": "检索归属库"}).json()["repo_id"]
        client.post("/ingest", json={
            "content": "kubernetes 归属检索", "event_type": "data", "repo_id": repo_id,
        })
        items = client.get(
            "/events", params={"repo_id": repo_id, "query": "kubernetes"}
        ).json()["items"]
        assert items and items[0]["repo_id"] == repo_id

    def test_nodes_list_items_carry_repo(self, repo_client):
        client, _mgr, _tmp = repo_client
        repo_id = client.post("/repos", json={"name": "节点归属库"}).json()["repo_id"]
        assert client.post(f"/repos/{repo_id}/activate").status_code == 200
        assert client.post(
            "/nodes", json={"title": "归属节点", "content": "内容"}
        ).status_code == 200

        items = client.get("/nodes", params={"repo_id": repo_id}).json()["items"]
        assert items and all(
            i["repo_id"] == repo_id and i["repo_name"] == "节点归属库" for i in items
        )

    @pytest.mark.asyncio
    async def test_joint_lists_carry_first_hit_repo(self, repo_client):
        client, mgr, _tmp = repo_client
        first = await mgr.create_repo("联合库一")
        second = await mgr.create_repo("联合库二")
        await mgr.entries[first.repo_id].event_store.insert_event("联合归属甲", "data")
        await mgr.entries[second.repo_id].event_store.insert_event("联合归属乙", "data")

        resp = client.get("/events", params={
            "repo_ids": f"{first.repo_id},{second.repo_id}", "limit": 50,
        })
        items = resp.json()["items"]
        names = {i["repo_name"] for i in items}
        assert names == {"联合库一", "联合库二"}
        assert all(i["repo_id"] in {first.repo_id, second.repo_id} for i in items)


# ── v1.32：书目收养 / 未加载原因可见 ─────────────────────────────────────────


class TestRepoAdopt:
    @pytest.mark.asyncio
    async def test_adopt_missing_graph_creates_empty_graph(self, repo_client):
        """只缺 graph.json：补一份带 format_version 的空图层，登记为 external 且可加载。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        target = _make_adopt_dir(tmp_path, with_db=True, with_json=False)

        resp = client.post("/repos/adopt", json={"root": str(target), "name": "收养库A"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == ["graph.json"]
        assert "已补建 graph.json" in data["message"]

        payload = json.loads((target / "graph.json").read_text(encoding="utf-8"))
        assert payload["format_version"] >= 1 and payload["nodes"] == {}
        record = mgr.records[data["repo_id"]]
        assert record.root_kind == "external" and record.db_path == str(target / "memory.db")
        # 补空后能正常加载（不是「登记了但打不开」）
        assert mgr.resolve(data["repo_id"]) is not None
        assert mgr.load_error_of(data["repo_id"]) == ""

    @pytest.mark.asyncio
    async def test_adopt_missing_db_creates_empty_db_with_schema(self, repo_client):
        """只缺 memory.db：建空库并建好当前 schema（含 events / graph_ops），json 原样保留。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        target = _make_adopt_dir(tmp_path, with_db=False, with_json=True)
        original_json = (target / "graph.json").read_text(encoding="utf-8")

        resp = client.post("/repos/adopt", json={"root": str(target), "name": "收养库B"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == ["memory.db"]
        assert (target / "memory.db").is_file()
        assert (target / "graph.json").read_text(encoding="utf-8") == original_json

        entry = mgr.resolve(data["repo_id"])
        assert entry is not None
        assert await entry.event_store.total_events() == 0
        cursor = await entry.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('events','graph_ops')"
        )
        assert {r["name"] for r in await cursor.fetchall()} == {"events", "graph_ops"}

    @pytest.mark.asyncio
    async def test_adopt_both_present_creates_nothing(self, repo_client):
        """两文件齐备：不补任何文件，只登记。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        target = _make_adopt_dir(tmp_path, with_db=True, with_json=True)
        before = (target / "graph.json").read_text(encoding="utf-8")

        data = client.post(
            "/repos/adopt", json={"root": str(target), "name": "收养库C"}
        ).json()
        assert data["created"] == []
        assert "未补建任何文件" in data["message"]
        assert (target / "graph.json").read_text(encoding="utf-8") == before
        assert data["repo_id"] in mgr.records

    @pytest.mark.asyncio
    async def test_adopt_missing_graph_replays_from_ops(self, repo_client):
        """补空图时顺带从 graph_ops 重放：能恢复就恢复（不是一律空图）。"""
        from core.graph_ops import record_ops
        from core.models import GraphNode, NodeMetadata, NodeType

        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        target = _make_adopt_dir(tmp_path, with_db=True, with_json=False)
        node = GraphNode(
            node_id="n_replay", title="重放回来的节点", content="内容",
            node_type=NodeType.data, confidence=0.5, source_refs=[],
            metadata=NodeMetadata(evidence_quote="内容"),
        )
        db = Database(str(target / "memory.db"))
        await db.connect()
        try:
            await record_ops(db.conn, [{"kind": "node_upsert", "node": node.model_dump()}])
        finally:
            await db.close()

        data = client.post(
            "/repos/adopt", json={"root": str(target), "name": "收养重放库"}
        ).json()
        assert data["created"] == ["graph.json"]
        entry = mgr.resolve(data["repo_id"])
        assert entry.graph_store.get_node("n_replay") is not None
        payload = json.loads((target / "graph.json").read_text(encoding="utf-8"))
        assert "n_replay" in payload["nodes"]

    @pytest.mark.asyncio
    async def test_adopt_empty_dir_rejected_400(self, repo_client):
        """一个文件都没有 → 400（那是「新建」不是「收养」），且说清目录里有什么。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        empty = Path(tmp_path.parent) / f"empty-{uuid.uuid4().hex[:8]}"
        empty.mkdir(parents=True, exist_ok=True)

        resp = client.post("/repos/adopt", json={"root": str(empty), "name": "空目录库"})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "既没有 memory.db 也没有 graph.json" in detail and "新建" in detail
        assert all(r.name != "空目录库" for r in mgr.records.values())

    @pytest.mark.asyncio
    async def test_adopt_already_registered_conflicts_409(self, repo_client):
        """该目录已登记为某书目 → 409（别重复登记同一份文件）。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        target = _make_adopt_dir(tmp_path, with_db=True, with_json=True)
        first = client.post(
            "/repos/adopt", json={"root": str(target), "name": "先登记的库"}
        )
        assert first.status_code == 200

        resp = client.post("/repos/adopt", json={"root": str(target), "name": "重复库"})
        assert resp.status_code == 409
        assert "已登记为库" in resp.json()["detail"]
        assert all(r.name != "重复库" for r in mgr.records.values())

    @pytest.mark.asyncio
    async def test_adopt_forbidden_dir_rejected(self, repo_client):
        """禁设清单照旧生效：数据根内 / repos 根。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        # 数据根内的目录（两文件齐备也照样拒绝——库文件会与登记表互相污染）
        inside = tmp_path / "inside-data-root"
        inside.mkdir(parents=True, exist_ok=True)
        (inside / "memory.db").write_bytes(b"")
        (inside / "graph.json").write_text('{"nodes": {}, "edges": []}', encoding="utf-8")

        for root in (str(inside), str(tmp_path / "repos")):
            resp = client.post("/repos/adopt", json={"root": root, "name": "禁设库"})
            assert resp.status_code == 400
            assert "禁设清单" in resp.json()["detail"]
        assert all(r.name != "禁设库" for r in mgr.records.values())

    @pytest.mark.asyncio
    async def test_adopt_missing_file_with_flag_false_rejected(self, repo_client):
        """adopt_missing=false：缺件即拒绝（用户想先自己查清楚）。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        target = _make_adopt_dir(tmp_path, with_db=True, with_json=False)
        resp = client.post("/repos/adopt", json={
            "root": str(target), "name": "不补库", "adopt_missing": False,
        })
        assert resp.status_code == 400
        assert "adopt_missing=false" in resp.json()["detail"]
        assert not (target / "graph.json").exists()


class TestRepoLoadError:
    @pytest.mark.asyncio
    async def test_load_error_reports_missing_registered_files(self, repo_client):
        """坏库有原因：登记文件缺失要说清缺哪个、在哪个目录。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        record = await mgr.create_repo("会坏的库")
        await mgr.update_repo(record.repo_id, managed=False)  # 先卸载，才能动文件
        Path(record.json_path).unlink()

        listed = next(
            r for r in client.get("/repos").json()["repos"] if r["repo_id"] == record.repo_id
        )
        assert listed["loaded"] is False
        assert "graph.json" in listed["load_error"]

        detail = client.get(f"/repos/{record.repo_id}").json()
        assert detail["load_error"] == listed["load_error"]

    def test_load_error_empty_for_loaded_repo(self, repo_client):
        """好库为空串（列表与详情都是）。"""
        client, _mgr, _tmp = repo_client
        listed = next(r for r in client.get("/repos").json()["repos"]
                      if r["repo_id"] == DEFAULT_REPO_ID)
        assert listed["loaded"] is True and listed["load_error"] == ""
        assert client.get(f"/repos/{DEFAULT_REPO_ID}").json()["load_error"] == ""

    @pytest.mark.asyncio
    async def test_load_error_explains_dormant_and_missing_dir(self, repo_client):
        """未加载的另两种可下手原因：休眠、库目录不存在。"""
        client, mgr, tmp_path = repo_client
        await mgr.initialize()
        dormant = await mgr.create_repo("休眠库")
        await mgr.update_repo(dormant.repo_id, managed=False)
        rows = {r["repo_id"]: r for r in client.get("/repos").json()["repos"]}
        assert "休眠" in rows[dormant.repo_id]["load_error"]

        broken = await mgr.create_repo("目录会消失的库")
        await mgr.update_repo(broken.repo_id, managed=False)
        import shutil as _shutil

        _shutil.rmtree(Path(broken.db_path).parent, ignore_errors=True)
        rows = {r["repo_id"]: r for r in client.get("/repos").json()["repos"]}
        assert "库目录不存在" in rows[broken.repo_id]["load_error"]
