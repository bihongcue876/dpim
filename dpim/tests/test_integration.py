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


class TestCreateNodeEndpoint:
    """POST /nodes 创建图节点"""

    def test_create_node_basic(self, test_app):
        resp = test_app.post("/nodes", json={"title": "测试节点", "content": "节点内容"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["node_id"]) == 16

    def test_create_node_shows_in_list(self, test_app):
        resp = test_app.post("/nodes", json={"title": "列表测试"})
        node_id = resp.json()["node_id"]
        nodes = test_app.get("/nodes?limit=100").json()
        ids = [n["node_id"] for n in nodes["items"]]
        assert node_id in ids

    def test_create_node_with_source_event(self, test_app):
        ev = test_app.post("/ingest", json={"content": "source event"})
        eid = ev.json()["event_id"]
        resp = test_app.post("/nodes", json={
            "title": "有来源的节点", "source_event_id": eid,
        })
        assert resp.status_code == 200
        detail = test_app.get(f"/nodes/{resp.json()['node_id']}").json()
        assert len(detail["source_refs"]) == 1
        assert detail["source_refs"][0]["event_id"] == eid

    def test_create_node_title_too_long(self, test_app):
        resp = test_app.post("/nodes", json={"title": "x" * 61})
        assert resp.status_code == 422  # Pydantic Field(max_length=60)


class TestClearGraphEndpoint:
    """DELETE /graph 清空图数据"""

    def test_clear_graph(self, test_app):
        test_app.post("/nodes", json={"title": "待清理节点"})
        nodes_before = test_app.get("/nodes?limit=100").json()
        assert nodes_before["total"] > 0
        resp = test_app.delete("/graph")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        nodes_after = test_app.get("/nodes?limit=100").json()
        assert nodes_after["total"] == 0


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

    def test_modify_status_raw_to_linked_rejected(self, test_app, event_store):
        """白名单：raw→linked 绕过管线，必须拒绝"""
        import asyncio

        from tests.factories import make_event
        eid = asyncio.run(make_event(event_store, "bypass attempt", status="raw"))
        resp = test_app.put(
            f"/events/{eid}/status", json={"status": "linked"},
        )
        assert resp.status_code == 400

    def test_modify_status_linked_to_indexed_rejected(self, test_app):
        """白名单：linked 为终态，不允许回退 indexed"""
        create = test_app.post("/ingest", json={"content": "terminal state"})
        eid = create.json()["event_id"]
        linked = test_app.put(
            f"/events/{eid}/status", json={"status": "linked"},
        )
        assert linked.status_code == 200
        resp = test_app.put(
            f"/events/{eid}/status", json={"status": "indexed"},
        )
        assert resp.status_code == 400

    def test_modify_status_indexed_to_raw_rejected(self, test_app):
        """白名单：indexed→raw 无意义，必须拒绝"""
        create = test_app.post("/ingest", json={"content": "back to raw"})
        eid = create.json()["event_id"]
        resp = test_app.put(
            f"/events/{eid}/status", json={"status": "raw"},
        )
        assert resp.status_code == 400


class TestModifyEventEndpoint:
    """PUT /events/{event_id} 事件内容修改"""

    def test_update_content(self, test_app):
        create = test_app.post("/ingest", json={"content": "original content"})
        eid = create.json()["event_id"]
        resp = test_app.put(f"/events/{eid}", json={"content": "updated content"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["event_id"] == eid

    def test_update_reflects_in_get(self, test_app):
        create = test_app.post("/ingest", json={"content": "before edit"})
        eid = create.json()["event_id"]
        test_app.put(f"/events/{eid}", json={"content": "after edit"})
        detail = test_app.get(f"/events/{eid}").json()
        assert detail["raw_content"] == "after edit"

    def test_update_nonexistent(self, test_app):
        resp = test_app.put("/events/nonexistent", json={"content": "nope"})
        assert resp.status_code == 404

    def test_update_refreshes_state_key(self, test_app):
        before = test_app.get("/state-hash").json()["hash"]
        create = test_app.post("/ingest", json={"content": "key test"})
        eid = create.json()["event_id"]
        test_app.put(f"/events/{eid}", json={"content": "updated"})
        after = test_app.get("/state-hash").json()["hash"]
        assert before != after  # key should change

    def test_update_fts_stays_searchable(self, test_app):
        create = test_app.post("/ingest", json={"content": "searchable phrase"})
        eid = create.json()["event_id"]
        test_app.put(f"/events/{eid}", json={"content": "updated searchable phrase"})
        # Search by updated content should still find it
        resp = test_app.post("/query", json={"query": "updated searchable"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert any("updated searchable" in r["snippet"] for r in results)


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


class TestSettingsEndpoint:
    """GET/PUT /settings — 含 BYOK 多模型网关配置项"""

    @pytest.fixture(autouse=True)
    def _isolate_dpim(self, tmp_path, monkeypatch):
        """重定向 dpim.json 到临时文件，避免 PUT 写入真实配置。"""
        from interface import api as api_mod

        monkeypatch.setattr(api_mod.settings, "config_file", str(tmp_path / "test_dpim.json"))
    BYOK_FIELDS = [
        "available_providers",
        "active_provider",
        "agent_mode",
        "agent_max_retries",
        "agent_cr_model",
        "agent_in_model",
        "agent_gr_model",
        "agent_meta_model",
    ]

    def test_get_settings_contains_byok_fields(self, test_app):
        resp = test_app.get("/settings")
        assert resp.status_code == 200
        data = resp.json()
        for field in self.BYOK_FIELDS:
            assert field in data, f"缺少配置项 {field}"

    def test_get_settings_available_providers_default(self, test_app, monkeypatch):
        from core.config import settings as s

        monkeypatch.setattr(s, "providers", {})
        resp = test_app.get("/settings")
        data = resp.json()
        assert data["available_providers"] == ["primary"]

    def test_put_providers_registers_and_active(self, test_app, monkeypatch):
        """PUT /settings 注册 provider + 设为活动 → 即时生效，无需重启。"""
        from core.config import settings as s

        monkeypatch.setattr(s, "providers", {})
        monkeypatch.setattr(s, "active_provider", "primary")
        r = test_app.put("/settings", json={
            "providers": {
                "qwen": {
                    "base_url": "http://localhost:5091/v1",
                    "api_key": "1",
                    "model": "Qwen3.5-9B",
                }
            },
            "active_provider": "qwen",
        })
        assert r.status_code == 200
        data = test_app.get("/settings").json()
        assert "qwen" in data["available_providers"]
        assert data["active_provider"] == "qwen"
        assert s.role_provider("cr").base_url == "http://localhost:5091/v1"

    def test_get_settings_active_model_fields(self, test_app):
        resp = test_app.get("/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "available_models" in data
        assert "active_model" in data

    def test_put_settings_active_model(self, test_app, monkeypatch):
        from core.config import settings as s

        monkeypatch.setattr(s, "providers", {
            "qwen": {"base_url": "http://localhost:5091/v1", "api_key": "1",
                     "models": ["Qwen3.5-9B", "Qwen3.5-35B-A3B"]},
        })
        monkeypatch.setattr(s, "active_provider", "qwen")
        monkeypatch.setattr(s, "active_model", "")
        r = test_app.put("/settings", json={"active_model": "Qwen3.5-35B-A3B"})
        assert r.status_code == 200
        assert s.role_model("cr") == "Qwen3.5-35B-A3B"

    def test_put_settings_updates_agent_mode(self, test_app):
        from core.config import settings as s

        old_mode = s.agent_mode
        old_active = s.active_provider
        try:
            resp = test_app.put("/settings", json={
                "agent_mode": "pipeline",
                "active_provider": "deepseek",
                "agent_cr_model": "deepseek-reasoner",
            })
            assert resp.status_code == 200
            assert s.agent_mode == "pipeline"
            assert s.active_provider == "deepseek"
            assert s.role_model("cr") == "deepseek-reasoner"
            # GET 反映运行时更新
            data = test_app.get("/settings").json()
            assert data["agent_mode"] == "pipeline"
            assert data["active_provider"] == "deepseek"
        finally:
            s.agent_mode = old_mode
            s.active_provider = old_active
            s.agent_cr_model = ""

    def test_put_settings_partial_ignores_missing(self, test_app):
        from core.config import settings as s

        old = s.agent_max_retries
        try:
            resp = test_app.put("/settings", json={"agent_max_retries": 5})
            assert resp.status_code == 200
            assert s.agent_max_retries == 5
        finally:
            s.agent_max_retries = old


class TestAgentLogsEndpoint:
    """GET /agent/logs — AI 调用日志观测"""

    def test_agent_logs_endpoint(self, test_app):
        from core.llm import clear_llm_logs, log_llm_call

        clear_llm_logs()
        log_llm_call("cr", "Qwen3.5-9B", "输入", "输出")
        resp = test_app.get("/agent/logs")
        assert resp.status_code == 200
        logs = resp.json()["logs"]
        assert isinstance(logs, list)
        assert logs and logs[0]["role"] == "cr"
        clear_llm_logs()

    def test_agent_logs_endpoint_full(self, test_app):
        from core.llm import clear_llm_logs, log_llm_call

        clear_llm_logs()
        log_llm_call("cr", "m", "入" * 3000, "出" * 3000)
        resp = test_app.get("/agent/logs?full=true")
        assert resp.status_code == 200
        logs = resp.json()["logs"]
        assert len(logs[0]["input"]) == 3000
        assert len(logs[0]["output"]) == 3000
        assert "input_preview" not in logs[0]
        clear_llm_logs()

    def test_agent_compensate_requires_orchestrator(self, test_app):
        """测试夹具中 orchestrator 未启动 → 503；生产环境 orchestrator 存在则触发。"""
        resp = test_app.post("/agent/compensate")
        assert resp.status_code == 503
