"""语义检索向量存储测试 — 序列化 / 余弦 / top-k / 增删查"""

import pytest

from core.embeddings import EmbeddingStore, cosine, pack_vector, unpack_vector


class TestVectorCodec:
    def test_pack_unpack_roundtrip(self):
        vec = [0.1, -0.5, 1.0, 3.14159]
        assert unpack_vector(pack_vector(vec)) == pytest.approx(vec, abs=1e-6)

    def test_pack_is_float32_blob(self):
        blob = pack_vector([1.0, 2.0])
        assert len(blob) == 8  # 2 × float32


class TestCosine:
    def test_parallel_vectors(self):
        assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_scaled_same_direction(self):
        assert cosine([1.0, 2.0], [2.0, 4.0]) == pytest.approx(1.0)

    def test_empty_or_mismatched(self):
        assert cosine([], []) == 0.0
        assert cosine([1.0], [1.0, 2.0]) == 0.0
        assert cosine([0.0, 0.0], [0.0, 0.0]) == 0.0  # 零向量


class TestEmbeddingStore:
    @pytest.mark.asyncio
    async def test_upsert_and_search_topk(self, db):
        estore = EmbeddingStore(db)
        await estore.upsert_event("e1", [1.0, 0.0, 0.0], "test-model")
        await estore.upsert_event("e2", [0.0, 1.0, 0.0], "test-model")
        await estore.upsert_node("n1", [0.9, 0.1, 0.0], "test-model")
        hits = await estore.search_event([1.0, 0.0, 0.0], limit=10)
        assert hits[0] == ("e1", pytest.approx(1.0))
        assert [k for k, _ in hits] == ["e1", "e2"]
        node_hits = await estore.search_node([1.0, 0.0, 0.0], limit=10)
        assert node_hits[0][0] == "n1"

    @pytest.mark.asyncio
    async def test_upsert_replace_idempotent(self, db):
        estore = EmbeddingStore(db)
        await estore.upsert_event("e1", [1.0, 0.0], "m")
        await estore.upsert_event("e1", [0.0, 1.0], "m")
        hits = await estore.search_event([0.0, 1.0], limit=10)
        assert hits[0][0] == "e1"
        assert len(hits) == 1

    @pytest.mark.asyncio
    async def test_search_limit(self, db):
        estore = EmbeddingStore(db)
        for i in range(5):
            await estore.upsert_event(f"e{i}", [float(i + 1), 0.0], "m")
        hits = await estore.search_event([1.0, 0.0], limit=2)
        assert len(hits) == 2
        assert hits[0][0] == "e0"  # 最接近 [1,0]

    @pytest.mark.asyncio
    async def test_delete(self, db):
        estore = EmbeddingStore(db)
        await estore.upsert_event("e1", [1.0, 0.0], "m")
        await estore.delete_event("e1")
        assert await estore.search_event([1.0, 0.0]) == []
        await estore.upsert_node("n1", [1.0, 0.0], "m")
        await estore.delete_node("n1")
        assert await estore.search_node([1.0, 0.0]) == []

    @pytest.mark.asyncio
    async def test_clear_all(self, db):
        estore = EmbeddingStore(db)
        await estore.upsert_event("e1", [1.0, 0.0], "m")
        await estore.upsert_node("n1", [1.0, 0.0], "m")
        await estore.clear_all()
        assert await estore.search_event([1.0, 0.0]) == []
        assert await estore.search_node([1.0, 0.0]) == []
