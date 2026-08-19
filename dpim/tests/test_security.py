"""安全加固测试集（协议 v1.13）— 密钥掩码 / API 认证 / 输入上限与值域 / 日志开关"""

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.security import (
    mask_provider_secret,
    mask_secret,
    resolve_provider_secret,
    resolve_secret,
)
from interface import api


@pytest.fixture
def test_app(db, event_store, graph_store):
    """Override api module globals with test instances, return TestClient."""
    api.db = db
    api.event_store = event_store
    api.graph_store = graph_store
    return TestClient(api.app)


@pytest.fixture(autouse=True)
def _isolate_dpim(tmp_path, monkeypatch):
    """重定向 dpim.json 到临时文件，避免 PUT 写入真实配置。"""
    monkeypatch.setattr(settings, "config_file", str(tmp_path / "test_dpim.json"))


# ──────────────────────────── 掩码工具单测 ────────────────────────────


class TestMaskSecret:
    def test_empty_returns_empty(self):
        assert mask_secret("") == ""

    def test_short_secret_fully_masked(self):
        # 短密钥（≤7 字符）头尾拼接几乎还原原文，必须全掩码
        for s in ["1", "sk-12", "abcdefg"]:
            assert mask_secret(s) == "****"

    def test_long_secret_head_tail_masked(self):
        key = "sk-1234567890abcdef"
        masked = mask_secret(key)
        assert masked == "sk-****cdef"
        assert key not in masked

    def test_mask_never_contains_plaintext_middle(self):
        key = "sk-SECRET_MIDDLE_SECRET"
        assert "SECRET" not in mask_secret(key)


class TestResolveSecret:
    def test_none_keeps_current(self):
        assert resolve_secret(None, "sk-old123456") == "sk-old123456"

    def test_empty_keeps_current(self):
        assert resolve_secret("", "sk-old123456") == "sk-old123456"

    def test_masked_echo_keeps_current(self):
        current = "sk-old123456"
        assert resolve_secret(mask_secret(current), current) == current

    def test_new_value_replaces(self):
        assert resolve_secret("sk-new999888", "sk-old123456") == "sk-new999888"


class TestProviderSecretHelpers:
    def test_mask_provider_secret_masks_key(self):
        entry = {"base_url": "http://x", "api_key": "sk-abcdef123456", "models": ["m1"]}
        masked = mask_provider_secret(entry)
        assert masked["api_key"] == "sk-****3456"
        assert masked["models"] == ["m1"]
        assert entry["api_key"] == "sk-abcdef123456"  # 原 dict 不被修改

    def test_mask_provider_secret_without_key(self):
        assert mask_provider_secret({"base_url": "http://x"}) == {"base_url": "http://x"}

    def test_resolve_provider_secret_keeps_masked_echo(self):
        current = {"base_url": "http://x", "api_key": "sk-real999888"}
        submitted = {"base_url": "http://x", "api_key": mask_secret("sk-real999888")}
        resolved = resolve_provider_secret(submitted, current)
        assert resolved["api_key"] == "sk-real999888"

    def test_resolve_provider_secret_empty_keeps_current(self):
        current = {"base_url": "http://x", "api_key": "sk-real999888"}
        resolved = resolve_provider_secret({"base_url": "http://x", "api_key": ""}, current)
        assert resolved["api_key"] == "sk-real999888"

    def test_resolve_provider_secret_new_value_replaces(self):
        current = {"base_url": "http://x", "api_key": "sk-old123456"}
        submitted = {"base_url": "http://x", "api_key": "sk-new999888"}
        resolved = resolve_provider_secret(submitted, current)
        assert resolved["api_key"] == "sk-new999888"

    def test_resolve_provider_secret_new_entry_empty_key_ok(self):
        # 全新 provider：空 key 合法（本地服务无需密钥）
        resolved = resolve_provider_secret({"base_url": "http://x", "api_key": ""}, None)
        assert resolved["api_key"] == ""

    def test_resolve_provider_secret_preserves_extra_fields(self):
        submitted = {
            "base_url": "http://x", "api_key": "", "max_tokens": 32000,
            "thinking_style": "top_level",
        }
        current = {"base_url": "http://y", "api_key": "sk-real999888"}
        resolved = resolve_provider_secret(submitted, current)
        assert resolved["max_tokens"] == 32000
        assert resolved["thinking_style"] == "top_level"


# ──────────────────────── GET /settings 掩码下发 ────────────────────────


class TestSettingsMasking:
    def test_get_settings_masks_llm_api_key(self, test_app, monkeypatch):
        real = "sk-plaintext-secret-999888"
        monkeypatch.setattr(settings, "llm_api_key", real)
        data = test_app.get("/settings").json()
        assert data["llm_api_key"] == "sk-****9888"
        assert real not in str(data)

    def test_get_settings_masks_provider_keys(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "providers", {
            "siliconflow": {
                "base_url": "https://api.siliconflow.cn/v1",
                "api_key": "sk-sf-secret-777666",
                "models": ["Qwen3.5-9B"],
            },
        })
        raw = test_app.get("/settings").text
        assert "sk-sf-secret-777666" not in raw
        assert "sk-****7666" in raw

    def test_get_settings_empty_key_no_mask_noise(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "llm_api_key", "")
        monkeypatch.setattr(settings, "providers", {})
        data = test_app.get("/settings").json()
        assert data["llm_api_key"] == ""


class TestSettingsPutMaskedIdempotent:
    """掩码幂等保留：前端把 GET 下发的掩码原样回传，不得清掉真钥。"""

    def test_put_masked_llm_api_key_keeps_original(self, test_app, monkeypatch):
        real = "sk-real-key-111222"
        monkeypatch.setattr(settings, "llm_api_key", real)
        r = test_app.put("/settings", json={"llm_api_key": mask_secret(real)})
        assert r.status_code == 200
        assert settings.llm_api_key == real

    def test_put_empty_llm_api_key_keeps_original(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "llm_api_key", "sk-real-key-333444")
        r = test_app.put("/settings", json={"llm_api_key": ""})
        assert r.status_code == 200
        assert settings.llm_api_key == "sk-real-key-333444"

    def test_put_new_llm_api_key_replaces(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "llm_api_key", "sk-old-key-555666")
        r = test_app.put("/settings", json={"llm_api_key": "sk-new-key-777888"})
        assert r.status_code == 200
        assert settings.llm_api_key == "sk-new-key-777888"

    def test_put_provider_masked_key_keeps_original(self, test_app, monkeypatch):
        real = "sk-provider-real-999000"
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "http://x/v1", "api_key": real, "models": ["m"]},
        })
        # GET 下发掩码 → 原样回传（含 base_url 修改）
        data = test_app.get("/settings").json()
        entry = dict(data["providers"]["sf"])
        entry["base_url"] = "http://y/v1"
        r = test_app.put("/settings", json={"providers": {"sf": entry}})
        assert r.status_code == 200
        assert settings.providers["sf"]["api_key"] == real
        assert settings.providers["sf"]["base_url"] == "http://y/v1"

    def test_put_provider_new_key_replaces(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "http://x/v1", "api_key": "sk-old-111222333"},
        })
        r = test_app.put("/settings", json={"providers": {
            "sf": {"base_url": "http://x/v1", "api_key": "sk-new-444555666"},
        }})
        assert r.status_code == 200
        assert settings.providers["sf"]["api_key"] == "sk-new-444555666"

    def test_masked_roundtrip_survives_read_modify_write(self, test_app, monkeypatch):
        """完整往返：GET(掩码) → PUT(掩码原样回传) → GET 仍掩码 → 真钥未变。"""
        real = "sk-roundtrip-key-123456"
        monkeypatch.setattr(settings, "llm_api_key", real)
        first = test_app.get("/settings").json()
        r = test_app.put("/settings", json={"llm_api_key": first["llm_api_key"]})
        assert r.status_code == 200
        second = test_app.get("/settings").json()
        assert second["llm_api_key"] == first["llm_api_key"]
        assert settings.llm_api_key == real


# ──────────────────────────── API 认证中间件 ────────────────────────────


class TestAuthMiddleware:
    def test_disabled_by_default_allows_all(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "")
        assert test_app.get("/health").status_code == 200
        assert test_app.get("/settings").status_code == 200

    def test_enabled_blocks_missing_header(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "test-secret-xyz")
        resp = test_app.get("/health")
        assert resp.status_code == 401
        assert "X-API-Key" in resp.text or "API-Key" in resp.text

    def test_enabled_blocks_wrong_header(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "test-secret-xyz")
        resp = test_app.get("/health", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_enabled_blocks_protects_sensitive_endpoints(self, test_app, monkeypatch):
        """敏感端点全覆盖：配置读取 / 日志 / 图清空 / 事件写入。"""
        monkeypatch.setattr(settings, "api_key", "test-secret-xyz")
        assert test_app.get("/settings").status_code == 401
        assert test_app.get("/agent/logs").status_code == 401
        assert test_app.delete("/graph").status_code == 401
        assert test_app.post("/ingest", json={"content": "x"}).status_code == 401
        assert test_app.put(
            "/settings", json={"llm_base_url": "http://attacker/v1"},
            headers={"X-API-Key": "guess"},
        ).status_code == 401

    def test_enabled_correct_header_passes(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "test-secret-xyz")
        h = {"X-API-Key": "test-secret-xyz"}
        assert test_app.get("/health", headers=h).status_code == 200
        assert test_app.get("/settings", headers=h).status_code == 200

    def test_auth_key_not_exposed_via_settings(self, test_app, monkeypatch):
        """API 认证密钥本身不得出现在 GET /settings 响应中。"""
        monkeypatch.setattr(settings, "api_key", "test-secret-xyz")
        h = {"X-API-Key": "test-secret-xyz"}
        raw = test_app.get("/settings", headers=h).text
        assert "test-secret-xyz" not in raw


# ──────────────────────── 输入上限与值域约束 ────────────────────────


class TestInputLimits:
    def test_ingest_content_over_limit_rejected(self, test_app):
        resp = test_app.post("/ingest", json={"content": "x" * 1_000_001})
        assert resp.status_code == 422

    def test_ingest_content_at_limit_accepted(self, test_app):
        resp = test_app.post("/ingest", json={"content": "a" * 1_000_000})
        assert resp.status_code == 200

    def test_put_event_content_over_limit_rejected(self, test_app):
        eid = test_app.post("/ingest", json={"content": "seed"}).json()["event_id"]
        resp = test_app.put(f"/events/{eid}", json={"content": "x" * 1_000_001})
        assert resp.status_code == 422

    def test_query_max_hops_out_of_range(self, test_app):
        assert test_app.post("/query", json={"query": "x", "max_hops": 0}).status_code == 422
        assert test_app.post("/query", json={"query": "x", "max_hops": 6}).status_code == 422
        assert test_app.post("/query", json={"query": "x", "max_hops": 1000}).status_code == 422

    def test_query_limit_out_of_range(self, test_app):
        assert test_app.post("/query", json={"query": "x", "limit": 101}).status_code == 422
        assert test_app.post("/query", json={"query": "x", "limit": 0}).status_code == 422

    def test_query_offset_negative(self, test_app):
        assert test_app.post("/query", json={"query": "x", "offset": -1}).status_code == 422

    def test_query_valid_bounds_accepted(self, test_app):
        assert test_app.post(
            "/query", json={"query": "x", "max_hops": 5, "limit": 100, "offset": 0},
        ).status_code == 200


class TestSettingsValidation:
    def test_agent_mode_invalid_rejected(self, test_app):
        assert test_app.put(
            "/settings", json={"agent_mode": "arbitrary-injection"},
        ).status_code == 422

    def test_log_level_invalid_rejected(self, test_app):
        assert test_app.put("/settings", json={"log_level": "TRACE"}).status_code == 422

    def test_numeric_out_of_range_rejected(self, test_app):
        assert test_app.put("/settings", json={"max_graph_hops": 99}).status_code == 422
        assert test_app.put("/settings", json={"rrf_k": 0}).status_code == 422
        assert test_app.put("/settings", json={"jaccard_threshold": 1.5}).status_code == 422
        assert test_app.put("/settings", json={"health_check_interval": 1}).status_code == 422
        assert test_app.put("/settings", json={"llm_timeout": -5}).status_code == 422
        assert test_app.put("/settings", json={"agent_max_retries": 99}).status_code == 422

    def test_valid_values_accepted(self, test_app):
        assert test_app.put("/settings", json={"rrf_k": 60}).status_code == 200


# ──────────────────────────── 日志全文开关 ────────────────────────────


class TestAgentLogsGate:
    def _long_log(self):
        from core.llm import clear_llm_logs, log_llm_call

        clear_llm_logs()
        long_input = "A" * 3000
        log_llm_call("cr", "test-model", long_input, "ok")
        return long_input

    def test_full_disabled_ignores_full_param(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "agent_logs_full", False)
        self._long_log()
        data = test_app.get("/agent/logs?full=true").json()
        log = data["logs"][0]
        assert len(log["output"]) <= 2000  # 截断版
        assert "input" not in log          # 无完整 input 字段

    def test_full_enabled_returns_complete(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "agent_logs_full", True)
        long_input = self._long_log()
        data = test_app.get("/agent/logs?full=true").json()
        log = data["logs"][0]
        assert log.get("input") == long_input

    def test_default_preview_truncated(self, test_app):
        self._long_log()
        data = test_app.get("/agent/logs").json()
        log = data["logs"][0]
        assert len(log["output"]) <= 2000
        assert "input" not in log
