"""存储保障测试（P4）：单实例锁、回收站留档与恢复、备份/校验、WAL 检查点。

对应此前「存储系统底线」的缺口：事件层零备份、无一致性校验入口、
跨进程互斥只是假设、物理删除无留档、WAL 无界增长。
"""

import json
import sqlite3
from pathlib import Path

import pytest

from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.lockfile import LockError, SingleInstanceLock
from core.maintenance import create_backup, list_backups, prune_backups, verify_storage
from core.models import GraphNode, NodeMetadata, NodeType, SourceRef
from core.repos import RepoManager
from core.trash import (
    archive_event,
    archive_node,
    list_archived,
    load_archived,
    trash_root,
)


def _node(node_id: str, title: str = "要点", event_id: str = "e1") -> GraphNode:
    return GraphNode(
        node_id=node_id,
        title=title,
        content="内容",
        node_type=NodeType.data,
        confidence=0.5,
        source_refs=[SourceRef(event_id=event_id, valid=True, hash="h")],
        metadata=NodeMetadata(evidence_quote="内容"),
    )


class TestSingleInstanceLock:
    def test_second_acquire_conflicts_and_release_frees(self, tmp_path):
        path = tmp_path / "x.lock"
        first = SingleInstanceLock(path)
        assert first.acquire() is True
        second = SingleInstanceLock(path)
        assert second.acquire() is False
        first.release()
        assert second.acquire() is True
        second.release()

    def test_acquire_or_raise_message_has_hint(self, tmp_path):
        path = tmp_path / "y.lock"
        holder = SingleInstanceLock(path)
        holder.acquire()
        try:
            with pytest.raises(LockError) as exc:
                SingleInstanceLock(path).acquire_or_raise(what="默认库")
            assert "另一个进程" in str(exc.value)
            assert "dpimCLI" in str(exc.value)  # 给出可操作的替代路径
        finally:
            holder.release()

    def test_reentrant_acquire_is_ok(self, tmp_path):
        lock = SingleInstanceLock(tmp_path / "z.lock")
        assert lock.acquire() is True
        assert lock.acquire() is True  # 同一实例重复获取不算冲突
        lock.release()

    def test_bind_default_twice_on_same_db_conflicts(self, tmp_path, monkeypatch):
        """两个 RepoManager 绑同一库 → 第二个被跨进程互斥挡住。"""
        from core.config import settings

        monkeypatch.setattr(settings, "memory_db_path", str(tmp_path / "memory.db"))
        monkeypatch.setattr(settings, "graph_json_path", str(tmp_path / "graph.json"))
        db = Database(str(tmp_path / "memory.db"))
        first = RepoManager()
        first.bind_default(db, EventStore(db), GraphStore(db, json_path=str(tmp_path / "graph.json")))
        try:
            with pytest.raises(LockError):
                RepoManager().bind_default(db, EventStore(db), GraphStore(db))
        finally:
            first.entries["rp_default"].lock.release()


class TestTrash:
    @pytest.mark.asyncio
    async def test_event_delete_archives_before_removing(self, real_db):
        es = EventStore(real_db)
        eid, _ = await es.insert("要被删掉的内容", "interaction")
        await es.delete(eid)
        assert await es.get(eid) is None
        archived = load_archived(real_db.db_path, "events", eid)
        assert archived is not None and archived["raw_content"] == "要被删掉的内容"

    @pytest.mark.asyncio
    async def test_restore_keeps_original_id(self, real_db):
        es = EventStore(real_db)
        eid, _ = await es.insert("恢复我", "data")
        event = await es.get(eid)
        await es.delete(eid)
        assert await es.restore(event) is True
        restored = await es.get(eid)
        assert restored is not None
        assert restored["event_id"] == eid  # 原 id 保留 → 图节点源证重新对上
        assert restored["raw_content"] == "恢复我"

    @pytest.mark.asyncio
    async def test_restored_event_is_searchable(self, real_db):
        es = EventStore(real_db)
        eid, _ = await es.insert_event("kubernetes 集群", "data")
        event = await es.get(eid)
        await es.delete(eid)
        await es.restore(event)
        rows = await es.search_fts("kubernetes")
        assert eid in {r["event_id"] for r in rows}

    def test_node_archive_and_list(self, real_db):
        archive_node(real_db.db_path, _node("n1", "红石机器").model_dump())
        rows = list_archived(real_db.db_path, "nodes")
        assert [r["item_id"] for r in rows] == ["n1"]
        data = load_archived(real_db.db_path, "nodes", "n1")
        assert data["title"] == "红石机器"

    def test_memory_db_skips_archive(self, db):
        """内存库没有可落档的位置：不留档也不报错。"""
        assert archive_event(db.db_path, {"event_id": "e1"}) is None
        assert list_archived(db.db_path) == []

    def test_archive_failure_does_not_raise(self, tmp_path):
        """留档失败不能阻断删除（目录不可写时只告警）。"""
        blocker = tmp_path / "blocked"
        blocker.write_text("我是文件不是目录", encoding="utf-8")
        assert archive_event(blocker / "memory.db", {"event_id": "e1"}) is None

    def test_empty_trash_lists_nothing(self, real_db):
        assert list_archived(real_db.db_path) == []
        assert trash_root(real_db.db_path).name == "trash"


class TestBackup:
    @pytest.mark.asyncio
    async def test_create_backup_copies_db_and_graph(self, real_db, tmp_path):
        es = EventStore(real_db)
        await es.insert("备份内容", "data")
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        gs.add_node(_node("n1"))
        await gs.save()

        result = await create_backup(real_db, gs, note="单测")
        target = Path(result["backup_dir"])
        assert (target / Path(real_db.db_path).name).exists()
        assert (target / "graph.json").exists()
        manifest = result["manifest"]
        assert manifest["total_events"] == 1
        assert manifest["total_nodes"] == 1
        assert manifest["note"] == "单测"
        assert manifest["db_bytes"] > 0

    @pytest.mark.asyncio
    async def test_backup_copy_is_a_usable_database(self, real_db, tmp_path):
        """备份出来的 db 必须是可直接打开的完整库（VACUUM INTO 的意义）。"""
        es = EventStore(real_db)
        eid, _ = await es.insert("校验备份可用性", "data")
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        result = await create_backup(real_db, gs)

        copy_path = Path(result["backup_dir"]) / Path(real_db.db_path).name
        raw = sqlite3.connect(str(copy_path))
        try:
            row = raw.execute(
                "SELECT raw_content FROM events WHERE event_id = ?", (eid,)
            ).fetchone()
            assert row[0] == "校验备份可用性"
        finally:
            raw.close()

    @pytest.mark.asyncio
    async def test_list_and_prune_keep_recent(self, real_db, tmp_path):
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        for i in range(3):
            await create_backup(real_db, gs, note=f"第{i}份", keep=0)
        assert len(list_backups(real_db.db_path)) == 3
        assert prune_backups(real_db.db_path, keep=1) == 2
        assert len(list_backups(real_db.db_path)) == 1

    @pytest.mark.asyncio
    async def test_memory_db_backup_rejected(self, db):
        gs = GraphStore(db, json_path=":memory:")
        with pytest.raises(RuntimeError):
            await create_backup(db, gs)


class TestVerify:
    @pytest.mark.asyncio
    async def test_detects_dangling_edges_in_file(self, real_db, tmp_path):
        """文件里端点不存在的边（v1.42：加载时会被跳过并清除）必须被校验抓到，
        而不是「加载时静默吞掉」——文件级残留要如实报出来。"""
        path = tmp_path / "graph.json"
        path.write_text(json.dumps({
            "format_version": 1,
            "nodes": {"n1": _node("n1").model_dump()},
            "edges": [{"source": "n1", "target": "ghost", "relation": "r",
                       "evidence_event_id": "e1"}],
        }, ensure_ascii=False), encoding="utf-8")
        gs = GraphStore(real_db, json_path=str(path))
        await gs.load()
        assert gs.total_nodes() == 1  # 空壳节点没被造出来

        result = await verify_storage(real_db, gs)
        names = {c["name"]: c for c in result["checks"]}
        assert names["no_dangling_edges_in_file"]["ok"] is False
        assert "1 条边" in names["no_dangling_edges_in_file"]["detail"]
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_clean_storage_passes(self, real_db, tmp_path):
        es = EventStore(real_db)
        eid, _ = await es.insert_event("一致性内容", "data")
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        gs.add_node(_node("n1", event_id=eid))  # 源证指向真实事件，否则悬空检查会失败
        await gs.save()
        # node_fts 由调用方同步（save 不做全量重建），这里显式对齐后校验才应为「通过」
        await gs.rebuild_node_fts()

        result = await verify_storage(real_db, gs)
        names = {c["name"]: c for c in result["checks"]}
        assert names["sqlite_integrity"]["ok"] is True
        assert names["events_fts_consistency"]["ok"] is True
        assert names["node_fts_consistency"]["ok"] is True
        assert names["ops_replay_matches_graph"]["ok"] is True
        assert names["no_dangling_source_refs"]["ok"] is True
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_detects_node_fts_drift(self, real_db, tmp_path):
        """node_fts 由调用方同步：漏了 upsert 必须被校验抓到（否则重启前静默搜不到）。"""
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        gs.add_node(_node("n1"))
        await gs.save()  # 故意不同步 node_fts

        result = await verify_storage(real_db, gs)
        names = {c["name"]: c for c in result["checks"]}
        assert names["node_fts_consistency"]["ok"] is False

    @pytest.mark.asyncio
    async def test_detects_fts_drift(self, real_db, tmp_path):
        """FTS 是手工同步的副本，掉一行必须被校验抓到。"""
        es = EventStore(real_db)
        eid, _ = await es.insert_event("会被删掉索引的行", "data")
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        await real_db.conn.execute("DELETE FROM events_fts WHERE event_id = ?", (eid,))
        await real_db.conn.commit()

        result = await verify_storage(real_db, gs)
        names = {c["name"]: c for c in result["checks"]}
        assert names["events_fts_consistency"]["ok"] is False
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_detects_dangling_source_ref(self, real_db, tmp_path):
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        gs.add_node(_node("n1"))  # 源证指向不存在的事件 e1
        await gs.save()
        result = await verify_storage(real_db, gs)
        names = {c["name"]: c for c in result["checks"]}
        assert names["no_dangling_source_refs"]["ok"] is False

    @pytest.mark.asyncio
    async def test_sizes_reported(self, real_db, tmp_path):
        gs = GraphStore(real_db, json_path=str(tmp_path / "graph.json"))
        await gs.load()
        await gs.save()
        result = await verify_storage(real_db, gs)
        assert result["sizes"]["db_bytes"] > 0
        assert "wal_bytes" in result["sizes"]


class TestWalGovernance:
    @pytest.mark.asyncio
    async def test_checkpoint_truncates_wal(self, real_db):
        es = EventStore(real_db)
        for i in range(20):
            await es.insert(f"写入第 {i} 条以撑大 WAL", "data")
        before = await real_db.wal_size()
        busy, log_frames, checkpointed = await real_db.checkpoint("TRUNCATE")
        after = await real_db.wal_size()
        assert busy == 0
        assert log_frames >= 0 and checkpointed >= 0
        assert after <= before  # 截断后 WAL 不增长（通常归零）

    @pytest.mark.asyncio
    async def test_sizes_available_for_memory_db(self, db):
        assert await db.wal_size() == 0
        assert await db.db_size() == 0
