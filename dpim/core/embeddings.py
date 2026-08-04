"""语义检索向量存储 — SQLite 向量表（float32 BLOB）+ 纯标准库余弦 top-k。

不引入 numpy 等新依赖：向量以 array('f') 序列化为 BLOB 存储，
余弦相似度用 math 计算（万级以下规模足够）。

表结构（database.py 统一建表）：
  event_embeddings(event_id PK, vector BLOB, dim, model, updated_at)
  node_embeddings(node_id PK, ...)
"""

import array
import math
from datetime import datetime, timezone

from core.database import Database


def pack_vector(vec: list[float]) -> bytes:
    """float32 序列化为 BLOB。"""
    return array.array("f", vec).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    """BLOB 还原为 float32 列表。"""
    return list(array.array("f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（-1..1）；空向量或维度不一致返回 0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class EmbeddingStore:
    """事件/节点向量表读写 + 余弦 top-k 检索。"""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def upsert_event(self, event_id: str, vector: list[float], model: str) -> None:
        await self.db.conn.execute(
            "INSERT OR REPLACE INTO event_embeddings"
            " (event_id, vector, dim, model, updated_at) VALUES (?,?,?,?,?)",
            (event_id, pack_vector(vector), len(vector), model, self._now()),
        )
        await self.db.conn.commit()

    async def upsert_node(self, node_id: str, vector: list[float], model: str) -> None:
        await self.db.conn.execute(
            "INSERT OR REPLACE INTO node_embeddings"
            " (node_id, vector, dim, model, updated_at) VALUES (?,?,?,?,?)",
            (node_id, pack_vector(vector), len(vector), model, self._now()),
        )
        await self.db.conn.commit()

    async def delete_event(self, event_id: str) -> None:
        await self.db.conn.execute(
            "DELETE FROM event_embeddings WHERE event_id = ?", (event_id,)
        )
        await self.db.conn.commit()

    async def delete_node(self, node_id: str) -> None:
        await self.db.conn.execute(
            "DELETE FROM node_embeddings WHERE node_id = ?", (node_id,)
        )
        await self.db.conn.commit()

    async def clear_all(self) -> None:
        await self.db.conn.execute("DELETE FROM event_embeddings")
        await self.db.conn.execute("DELETE FROM node_embeddings")
        await self.db.conn.commit()

    async def search_event(
        self, query_vec: list[float], limit: int = 100
    ) -> list[tuple[str, float]]:
        """事件向量余弦 top-k，返回 [(event_id, score)] 降序。"""
        cursor = await self.db.conn.execute(
            "SELECT event_id, vector FROM event_embeddings"
        )
        rows = await cursor.fetchall()
        scored = [
            (row["event_id"], cosine(query_vec, unpack_vector(row["vector"])))
            for row in rows
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def search_node(
        self, query_vec: list[float], limit: int = 100
    ) -> list[tuple[str, float]]:
        """节点向量余弦 top-k，返回 [(node_id, score)] 降序。"""
        cursor = await self.db.conn.execute(
            "SELECT node_id, vector FROM node_embeddings"
        )
        rows = await cursor.fetchall()
        scored = [
            (row["node_id"], cosine(query_vec, unpack_vector(row["vector"])))
            for row in rows
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]
