"""信息线层：事件 CRUD + FTS5 索引维护"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone

from core.database import Database


def _make_event_id() -> str:
    ts = int(time.time() * 1000)
    rand = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    return f"{ts}-{rand}"


def _content_hash(content: str) -> str:
    return hashlib.blake2s(content.encode(), digest_size=8).hexdigest()


class EventStore:
    def __init__(self, db: Database):
        self.db = db

    async def insert(self, raw_content: str, event_type: str = "auto") -> tuple[str, str]:
        event_id = _make_event_id()
        created_at = datetime.now(timezone.utc).isoformat()
        c_hash = _content_hash(raw_content)
        et = event_type if event_type != "auto" else "interaction"
        await self.db.conn.execute(
            "INSERT INTO events (event_id,created_at,raw_content,content_hash,event_type)"
            " VALUES (?,?,?,?,?)",
            (event_id, created_at, raw_content, c_hash, et),
        )
        await self.db.conn.commit()
        return event_id, "raw"

    async def get(self, event_id: str) -> dict | None:
        cursor = await self.db.conn.execute(
            "SELECT * FROM events WHERE event_id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["graph_refs"] = json.loads(d.get("graph_refs", "[]"))
        return d

    async def update_status(self, event_id: str, status: str, graph_refs: list[str] | None = None):
        if graph_refs is not None:
            await self.db.conn.execute(
                "UPDATE events SET status = ?, graph_refs = ? WHERE event_id = ?",
                (status, json.dumps(graph_refs), event_id),
            )
        else:
            await self.db.conn.execute(
                "UPDATE events SET status = ? WHERE event_id = ?",
                (status, event_id),
            )
        await self.db.conn.commit()

    async def delete(self, event_id: str) -> dict | None:
        event = await self.get(event_id)
        if event is None:
            return None
        await self.db.conn.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
        await self.db.conn.execute("DELETE FROM events_fts WHERE event_id = ?", (event_id,))
        await self.db.conn.commit()
        return event

    async def list_by_status(self, status: str) -> list[dict]:
        cursor = await self.db.conn.execute(
            "SELECT * FROM events WHERE status = ? ORDER BY created_at ASC", (status,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count_by_status(self) -> dict[str, int]:
        cursor = await self.db.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM events GROUP BY status"
        )
        rows = await cursor.fetchall()
        counts = {"raw": 0, "indexed": 0, "linked": 0, "failed": 0, "skipped": 0}
        for r in rows:
            counts[r["status"]] = r["cnt"]
        return counts

    async def total_events(self) -> int:
        cursor = await self.db.conn.execute("SELECT COUNT(*) as cnt FROM events")
        row = await cursor.fetchone()
        return row["cnt"]

    async def last_event_at(self) -> str | None:
        cursor = await self.db.conn.execute(
            "SELECT created_at FROM events ORDER BY created_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row["created_at"] if row else None

    async def insert_event(self, raw_content: str, event_type: str = "auto") -> tuple[str, str]:
        """写入事件 → 建 FTS 索引 → 标记 indexed，一条调用完成完整写入。

        外部无需再手动调用 insert_fts 和 update_status。
        返回 (event_id, "indexed")。
        """
        eid, _ = await self.insert(raw_content, event_type)
        await self.insert_fts(eid, raw_content)
        await self.update_status(eid, "indexed")
        return eid, "indexed"

    async def insert_fts(self, event_id: str, raw_content: str):
        await self.db.conn.execute(
            "INSERT INTO events_fts (event_id, raw_content) VALUES (?, ?)",
            (event_id, raw_content),
        )
        await self.db.conn.commit()

    async def search_fts(self, query: str, limit: int = 100) -> list[dict]:
        cursor = await self.db.conn.execute(
            "SELECT e.*, rank FROM events_fts f JOIN events e ON f.event_id = e.event_id "
            "WHERE events_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete_with_protection(
        self, event_id: str, graph_store,
    ) -> dict:
        """Delete event with source_ref protection for system/data nodes."""
        event = await self.get(event_id)
        if event is None:
            return {"status": "not_found"}
        refs = event.get("graph_refs", [])
        for nid in refs:
            node = graph_store.get_node(nid)
            if node is None:
                continue
            graph_store.invalidate_source_ref(event_id)
            has_other = any(
                sr.valid for sr in node.source_refs if sr.event_id != event_id
            )
            if not has_other:
                if node.node_type.value in ("system", "data"):
                    return {
                        "status": "protected",
                        "node_id": nid,
                        "node_type": node.node_type.value,
                    }
                graph_store.remove_node(nid)
                await graph_store.delete_node_fts(nid)
        await self.delete(event_id)
        return {"status": "ok"}
