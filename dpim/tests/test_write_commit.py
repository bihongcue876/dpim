"""写请求收口中间件测试：落盘 + 状态密钥刷新 + 写操作流水。

覆盖 `interface/api.py` 的 `write_commit` 三项收口语义：

- 成功写 → 脏图落盘、状态密钥刷新
- 失败写（4xx）→ 密钥不刷新（`StateKey.refresh()` 生成随机 UUID，误刷会让前端无谓重取）
- `POST /feedback` 原先只 flush 不刷密钥（陈旧密钥缺陷）→ 现在自动刷新
"""

import pytest
from fastapi.testclient import TestClient

from core.graph_store import GraphStore
from core.models import GraphNode, NodeMetadata, NodeType, SourceRef
from core.state import get_key
from interface import api, deps


@pytest.fixture
def client(db, event_store, graph_store):
    deps.db = db
    deps.event_store = event_store
    deps.graph_store = graph_store
    deps.repos = None
    return TestClient(api.app)


def _node(
    node_id: str,
    confidence: float = 0.5,
    node_type: NodeType = NodeType.interaction,
) -> GraphNode:
    """收口测试节点：默认 interaction（system/data 对 /feedback 是 no-op）。"""
    return GraphNode(
        node_id=node_id,
        title="收口要点",
        content="内容",
        node_type=node_type,
        confidence=confidence,
        source_refs=[SourceRef(event_id="e1", valid=True, hash="h")],
        metadata=NodeMetadata(evidence_quote="内容"),
    )


class TestStateKeyRefresh:
    def test_successful_write_refreshes_key(self, client):
        before = get_key()
        resp = client.post(
            "/ingest", json={"content": "收口测试", "event_type": "interaction"}
        )
        assert resp.status_code == 200
        assert get_key() != before

    def test_failed_write_keeps_key(self, client):
        before = get_key()
        resp = client.post("/ingest", json={"content": "缺 event_type"})
        assert resp.status_code == 422
        assert get_key() == before

    def test_read_request_does_not_refresh_key(self, client):
        before = get_key()
        assert client.get("/health").status_code == 200
        assert get_key() == before

    def test_feedback_refreshes_key(self, client, graph_store):
        """缺陷修复：POST /feedback 原先只 flush 不刷密钥，前端察觉不到置信度变化。"""
        graph_store.add_node(_node("n_fb"))
        before = get_key()
        resp = client.post("/feedback", json={"result_id": "n_fb", "accepted": True})
        assert resp.status_code == 200
        assert get_key() != before


class TestWriteFlush:
    def test_write_flushes_dirty_graph(self, client, graph_store):
        graph_store.add_node(_node("n_dirty"))
        assert graph_store.dirty is True
        resp = client.post("/feedback", json={"result_id": "n_dirty", "accepted": True})
        assert resp.status_code == 200
        assert graph_store.dirty is False  # 中间件已统一落盘

    def test_read_request_does_not_flush(self, client, graph_store):
        graph_store.add_node(_node("n_untouched"))
        assert client.get("/health").status_code == 200
        assert graph_store.dirty is True  # 读请求不落盘，脏位保留

    @pytest.mark.asyncio
    async def test_write_persists_to_disk(self, client, graph_store, db):
        graph_store.add_node(_node("n_persist"))
        resp = client.post("/feedback", json={"result_id": "n_persist", "accepted": True})
        assert resp.status_code == 200
        reloaded = GraphStore(db, json_path=graph_store.json_path)
        await reloaded.load()
        node = reloaded.get_node("n_persist")
        assert node is not None
        assert node.confidence > 0.5  # 反馈后的新置信度已落盘
