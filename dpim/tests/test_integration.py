"""API 集成测试 — 使用 FastAPI TestClient 直接测试端点"""

import pytest
from fastapi.testclient import TestClient

from core.models import (
    GraphNode,
    NodeMetadata,
    NodeType,
    SourceRef,
)
from interface import api


@pytest.fixture
def test_app(db, event_store, graph_store):
    """Override api module globals with test instances, return TestClient."""
    api.db = db
    api.event_store = event_store
    api.graph_store = graph_store
    client = TestClient(api.app)
    return client


class TestIngestEndpoint:
    def test_ingest_returns_event_id(self, test_app):
        resp = test_app.post("/ingest", json={"content": "test event"})
        assert resp.status_code == 200
        data = resp.json()
        assert "event_id" in data
        assert data["status"] == "indexed"

    def test_ingest_with_type(self, test_app):
        resp = test_app.post("/ingest", json={
            "content": "data content", "event_type": "data",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "indexed"

    def test_ingest_empty_content(self, test_app):
        resp = test_app.post("/ingest", json={"content": ""})
        assert resp.status_code == 200


class TestHealthEndpoint:
    def test_health_returns_ok(self, test_app):
        resp = test_app.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "layers" in data
        assert "event_line" in data["layers"]
        assert "knowledge_graph" in data["layers"]


class TestQueryEndpoint:
    def test_query_returns_results(self, test_app):
        test_app.post("/ingest", json={"content": "Python programming"})
        resp = test_app.post("/query", json={"query": "Python"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_query_no_results(self, test_app):
        resp = test_app.post("/query", json={"query": "zzz_nonexistent"})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 0


class TestDeleteEventEndpoint:
    def test_delete_nonexistent(self, test_app):
        resp = test_app.delete("/events/nonexistent")
        assert resp.status_code == 404

    def test_delete_orphan_event(self, test_app):
        create = test_app.post("/ingest", json={"content": "delete me"})
        eid = create.json()["event_id"]
        resp = test_app.delete(f"/events/{eid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_delete_protected_event(self, test_app):
        create = test_app.post("/ingest", json={"content": "protected source"})
        eid = create.json()["event_id"]
        api.graph_store.add_node(GraphNode(
            node_id="protected_node",
            title="Protected",
            content="data",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id=eid, valid=True, hash="h")],
            confidence=0.9,
            metadata=NodeMetadata(evidence_quote="test"),
        ))
        import json as _json
        await api.event_store.db.conn.execute(
            "UPDATE events SET graph_refs = ? WHERE event_id = ?",
            (_json.dumps(["protected_node"]), eid),
        )
        await api.event_store.db.conn.commit()
        resp = test_app.delete(f"/events/{eid}")
        assert resp.status_code == 409


class TestDeleteNodeEndpoint:
    def test_delete_nonexistent_node(self, test_app):
        resp = test_app.delete("/nodes/nonexistent")
        assert resp.status_code == 404

    def test_delete_node_no_refs(self, test_app):
        api.graph_store.add_node(GraphNode(
            node_id="orphan", title="Orphan", content="alone",
            node_type=NodeType.interaction,
            source_refs=[],
            confidence=0.5,
            metadata=NodeMetadata(evidence_quote=""),
        ))
        resp = test_app.delete("/nodes/orphan")
        assert resp.status_code == 200


class TestModifyNodeEndpoint:
    def test_modify_node(self, test_app):
        api.graph_store.add_node(GraphNode(
            node_id="mod_me", title="Original", content="old content",
            node_type=NodeType.interaction,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h")],
            confidence=0.8,
            metadata=NodeMetadata(evidence_quote="test"),
        ))
        resp = test_app.put("/nodes/mod_me", json={"content": "new content"})
        assert resp.status_code == 200
        node = api.graph_store.get_node("mod_me")
        assert node.content == "new content"
        assert node.confidence == 0.7

    def test_modify_system_node_forbidden(self, test_app):
        api.graph_store.add_node(GraphNode(
            node_id="sys_node", title="System", content="protected",
            node_type=NodeType.system,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h")],
            confidence=1.0,
            metadata=NodeMetadata(evidence_quote="test"),
        ))
        resp = test_app.put("/nodes/sys_node", json={"content": "hack"})
        assert resp.status_code == 403


class TestModifyEventStatusEndpoint:
    def test_modify_status_allowed(self, test_app):
        create = test_app.post("/ingest", json={"content": "status test"})
        eid = create.json()["event_id"]
        resp = test_app.put(
            f"/events/{eid}/status", json={"status": "skipped"},
        )
        assert resp.status_code == 200
        assert resp.json()["new_status"] == "skipped"

    def test_modify_status_nonexistent(self, test_app):
        resp = test_app.put(
            "/events/nonexistent/status", json={"status": "linked"},
        )
        assert resp.status_code == 404


class TestFeedbackEndpoint:
    def test_feedback_accepted(self, test_app):
        api.graph_store.add_node(GraphNode(
            node_id="fb_node", title="Feedback", content="test",
            node_type=NodeType.interaction,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h")],
            confidence=0.5,
            metadata=NodeMetadata(evidence_quote="test"),
        ))
        resp = test_app.post("/feedback", json={
            "result_id": "fb_node", "accepted": True,
        })
        assert resp.status_code == 200
        node = api.graph_store.get_node("fb_node")
        assert node.confidence == 0.51  # 0.5 + 0.01
