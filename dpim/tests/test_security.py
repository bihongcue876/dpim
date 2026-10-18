"""安全加固测试集（协议 v1.13）— 密钥掩码 / API 认证 / 输入上限与值域 / 日志开关"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.security import (
    mask_provider_secret,
    mask_secret,
    resolve_provider_secret,
    resolve_secret,
)
from core.state import ai_state
from interface import api, deps
from interface.routers import settings as settings_mod


@pytest.fixture
def test_app(db, event_store, graph_store):
    """Override api module globals with test instances, return TestClient."""
    deps.db = db
    deps.event_store = event_store
    deps.graph_store = graph_store
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

    def test_mask_shape_never_stored_even_without_current(self):
        """v1.33：掩码形状的值绝不当真钥落库（现值为空时同样拒绝）。"""
        assert resolve_secret("****", "") == ""
        assert resolve_secret("sk-****abcd", "") == ""
        assert resolve_secret("sk-****abcd", "sk-real999888") == "sk-real999888"

    def test_real_key_with_asterisk_not_mask_shaped_still_accepted(self):
        # 只有「头3 + **** + 尾4」或全掩码才判定为掩码，真钥照常替换
        assert resolve_secret("sk-abc*def1234", "sk-old123456") == "sk-abc*def1234"
        assert resolve_secret("sk-***abc1234", "sk-old123456") == "sk-***abc1234"


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

    def test_resolve_provider_secret_new_entry_drops_mask(self):
        """v1.33 修复：新条目（重命名/复制）带过来的掩码视为「未填」。

        旧实现 `key == mask_secret("")` 恒为假（`mask_secret("")` 是空串），
        等于没拦 —— 掩码被当真钥写进 dpim.json，AI 侧 401 而界面显示「已设置」。
        """
        assert resolve_provider_secret({"api_key": "****"}, None)["api_key"] == ""
        assert (
            resolve_provider_secret({"api_key": "sk-****abcd"}, None)["api_key"] == ""
        )
        # 真钥照常保留
        assert (
            resolve_provider_secret({"api_key": "sk-real999888"}, None)["api_key"]
            == "sk-real999888"
        )

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

    def test_get_settings_no_llm_identity_fields(self, test_app, monkeypatch):
        """v1.34：不再下发主配置身份字段（那套已删除），改为未配置状态字段。"""
        monkeypatch.setattr(settings, "providers", {})
        data = test_app.get("/settings").json()
        for gone in (
            "llm_base_url",
            "llm_api_key",
            "llm_model_name",
            "llm_timeout",
            "llm_max_tokens",
            "llm_enable_thinking",
            "llm_thinking_budget",
        ):
            assert gone not in data
        assert data["available_providers"] == []
        assert data["llm_configured"] is False
        assert "未配置任何 AI 提供商" in data["llm_unavailable_reason"]

    def test_get_settings_configured_true_with_model(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "https://api.siliconflow.cn/v1", "api_key": "k", "models": ["m1"]},
        })
        monkeypatch.setattr(settings, "active_provider", "sf")
        data = test_app.get("/settings").json()
        assert data["llm_configured"] is True
        assert data["llm_unavailable_reason"] == ""
        assert data["available_models"] == ["m1"]


class TestSettingsPutMaskedIdempotent:
    """掩码幂等保留：前端把 GET 下发的掩码原样回传，不得清掉真钥。"""

    def test_put_storage_paths_updates_and_persists(self, test_app, monkeypatch, tmp_path):
        """v1.16：存储路径经 PUT /settings 修改并持久化 dpim.json（白名单修复回归）。

        v1.36：来源须为 file/default —— 若被 env 顶掉（本机 dpim/.env 就有
        `DPIM_MEMORY_DB_PATH`），PUT 不再写入内存而是如实报 `ignored_by_env`。
        """
        monkeypatch.setattr(settings, "_sources", {
            **settings.config_sources,
            "memory_db_path": "default",
            "graph_json_path": "default",
        })
        old_db, old_json = settings.memory_db_path, settings.graph_json_path
        new_db, new_json = str(tmp_path / "new.db"), str(tmp_path / "new.json")
        try:
            r = test_app.put(
                "/settings",
                json={"memory_db_path": new_db, "graph_json_path": new_json},
            )
            assert r.status_code == 200
            # 白名单修复：此前字段不在 SettingsUpdateRequest，修改被静默丢弃
            assert settings.memory_db_path == new_db
            assert settings.graph_json_path == new_json
            # 持久化断言：storage 段落盘 dpim.json（_isolate_dpim 已重定向到 tmp）
            data = json.loads(Path(settings.config_file).read_text(encoding="utf-8"))
            assert data["storage"]["memory_db_path"] == new_db
            assert data["storage"]["graph_json_path"] == new_json
        finally:
            settings.memory_db_path, settings.graph_json_path = old_db, old_json

    def test_put_storage_path_env_locked_is_reported_not_applied(self, test_app, monkeypatch):
        """env 锁定的配置项：界面改动不写入内存，响应里点名是哪个环境变量顶掉的。"""
        monkeypatch.setattr(settings, "_sources", {
            **settings.config_sources,
            "memory_db_path": "env:DPIM_MEMORY_DB_PATH",
        })
        before = settings.memory_db_path
        r = test_app.put("/settings", json={"memory_db_path": "X:/nope.db"})
        assert r.status_code == 200
        assert r.json()["ignored_by_env"] == ["memory_db_path(DPIM_MEMORY_DB_PATH)"]
        assert settings.memory_db_path == before

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
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "http://x/v1", "api_key": real, "models": ["m"]},
        })
        monkeypatch.setattr(settings, "active_provider", "sf")
        first = test_app.get("/settings").json()
        r = test_app.put("/settings", json={"providers": {"sf": first["providers"]["sf"]}})
        assert r.status_code == 200
        second = test_app.get("/settings").json()
        assert second["providers"]["sf"]["api_key"] == first["providers"]["sf"]["api_key"]
        assert settings.providers["sf"]["api_key"] == real

    def test_removed_llm_fields_rejected_with_hint(self, test_app, monkeypatch):
        """v1.35：旧的 llm_* 主配置字段**明确 422**（不静默丢弃）。

        旧界面（浏览器缓存旧包）填了「主配置」后提交，若静默忽略会显示「已保存」
        而实际什么都没改——用户看到的现象就是「以前能配、现在怎么都不生效」。
        """
        monkeypatch.setattr(settings, "providers", {})
        r = test_app.put("/settings", json={
            "llm_base_url": "http://legacy/v1",
            "llm_api_key": "sk-new-key-777888",
            "llm_model_name": "legacy-model",
        })
        assert r.status_code == 422
        detail = r.json()["detail"]
        locs = [d["loc"][-1] for d in detail]
        assert locs == ["llm_base_url", "llm_api_key", "llm_model_name"]
        assert "providers" in detail[0]["msg"] and "刷新" in detail[0]["msg"]
        for gone in ("llm_base_url", "llm_api_key", "llm_model_name"):
            assert not hasattr(settings, gone)  # 不会被悄悄写回运行时

    def test_put_provider_clear_api_key_removes_stored_key(self, test_app, monkeypatch):
        """v1.35：`clear_api_key: true` = 显式清空（「空串 = 保持现值」使清空无出路）。"""
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "http://x/v1", "api_key": "sk-to-be-cleared-123456"},
        })
        r = test_app.put("/settings", json={"providers": {
            "sf": {
                "base_url": "http://x/v1",
                "api_key": "",  # 空串本身仍表示「保持」
                "clear_api_key": True,
            },
        }})
        assert r.status_code == 200
        assert settings.providers["sf"]["api_key"] == ""
        # 标记本身不入库
        assert "clear_api_key" not in settings.providers["sf"]
        data = json.loads(Path(settings.config_file).read_text(encoding="utf-8"))
        assert data["providers"]["sf"]["api_key"] == ""
        assert "clear_api_key" not in data["providers"]["sf"]
        # GET 下发空密钥（界面显示「未设置」）
        assert test_app.get("/settings").json()["providers"]["sf"]["api_key"] == ""

    def test_clear_api_key_false_still_keeps_key(self, test_app, monkeypatch):
        """`clear_api_key: false`（或不带该字段）= 保持现值，掩码回传也不清钥。"""
        real = "sk-keepme-123456789"
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "http://x/v1", "api_key": real},
        })
        masked = test_app.get("/settings").json()["providers"]["sf"]["api_key"]
        r = test_app.put("/settings", json={"providers": {
            "sf": {"base_url": "http://x/v1", "api_key": masked, "clear_api_key": False},
        }})
        assert r.status_code == 200
        assert settings.providers["sf"]["api_key"] == real
        assert "clear_api_key" not in settings.providers["sf"]

    def test_put_new_provider_with_clear_flag_is_plain_empty(self, test_app, monkeypatch):
        """新条目带 `clear_api_key`（本地服务无需密钥）：结果就是空密钥，不应报错。"""
        monkeypatch.setattr(settings, "providers", {})
        r = test_app.put("/settings", json={"providers": {
            "local": {
                "base_url": "http://localhost:5091/v1",
                "api_key": "sk-****abcd",  # 复制粘贴带来的掩码
                "models": ["Qwen3.5-9B-Q4_K_M"],
                "clear_api_key": True,
            },
        }, "active_provider": "local"})
        assert r.status_code == 200
        assert settings.providers["local"]["api_key"] == ""
        assert settings.active_provider == "local"

    def test_put_provider_registry_persisted_to_dpim_json(self, test_app, monkeypatch):
        """v1.34：前端登记的提供商整体落盘，重启后仍在（含地址/密钥/模型列表）。"""
        monkeypatch.setattr(settings, "providers", {})
        monkeypatch.setattr(settings, "active_provider", "")
        r = test_app.put("/settings", json={
            "providers": {
                "siliconflow": {
                    "base_url": "https://api.siliconflow.cn/v1",
                    "api_key": "sk-frontend-entered-123456",
                    "models": ["deepseek-ai/DeepSeek-V4-Flash"],
                },
            },
            "active_provider": "siliconflow",
            "active_model": "deepseek-ai/DeepSeek-V4-Flash",
        })
        assert r.status_code == 200
        data = json.loads(Path(settings.config_file).read_text(encoding="utf-8"))
        entry = data["providers"]["siliconflow"]
        # 真钥落盘（dpim/dpim.json 在 .gitignore 内，不出仓库）
        assert entry["api_key"] == "sk-frontend-entered-123456"
        assert entry["base_url"] == "https://api.siliconflow.cn/v1"
        assert data["active_provider"] == "siliconflow"
        assert "llm" not in data  # v1.34：不再写 llm 段
        assert settings.llm_configured is True

    def test_put_new_provider_with_mask_does_not_store_mask(self, test_app, monkeypatch):
        """v1.33：新条目带过来的掩码不得当真钥落盘（重命名/复制条目的路径）。"""
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "http://x/v1", "api_key": "sk-real-abc123456"},
        })
        masked = test_app.get("/settings").json()["providers"]["sf"]["api_key"]
        r = test_app.put("/settings", json={"providers": {
            "sf": {"base_url": "http://x/v1", "api_key": "sk-real-abc123456"},
            "sf-copy": {"base_url": "http://x/v1", "api_key": masked},  # 复制条目带掩码
        }})
        assert r.status_code == 200
        assert settings.providers["sf-copy"]["api_key"] == ""  # 掩码被丢弃，不是 "sk-****3456"


# ─────────────── 前端可配置面（v1.36：改了就真的存下来、且看得见来源）───────────────


class TestConfigSurface:
    """前端配置后端：① 每一项都落盘（不是只改内存）；② 来源可见（env 顶掉的必须报出来）。"""

    @pytest.fixture(autouse=True)
    def _restore_settings(self):
        """`settings` 是全局单例：本类会真的改运行时配置，测完必须还原。

        否则「高水位 / 维护阈值」被改过的值会污染后续模块（size_pressure 等判定）。
        """
        saved = dict(vars(settings))
        saved_sources = dict(settings._sources)
        yield
        for key, value in saved.items():
            setattr(settings, key, value)
        settings._sources.clear()
        settings._sources.update(saved_sources)

    def test_get_settings_exposes_new_fields_and_sources(self, test_app):
        data = test_app.get("/settings").json()
        for field in (
            "max_raw_content", "compensate_check_interval", "agent_maintain_auto",
            "agent_maintain_max_nodes", "agent_cmdmsg_max_rounds", "agent_cr_skip_chars",
            "log_retention_days", "log_jsonl", "agent_logs_full",
            "wal_checkpoint_interval", "wal_checkpoint_bytes", "llm_structured_mode",
            "graph_ops_retention", "trash_retention_days",
        ):
            assert field in data, f"{field} 未下发（界面就配不了它）"
        assert data["config_file"] == settings.config_file
        assert data["log_dir"]
        assert isinstance(data["config_sources"], dict)
        assert data["config_sources"]["max_graph_hops"] in ("file", "default") or (
            data["config_sources"]["max_graph_hops"].startswith("env:")
        )

    def test_put_persists_previously_memory_only_fields(self, test_app, monkeypatch):
        """v1.36 真缺陷修复：这 6 项此前只改内存（重启即回默认），现在必须落盘。"""
        monkeypatch.setattr(settings, "max_graph_hops", 2)
        r = test_app.put("/settings", json={
            "max_graph_hops": 4,
            "rrf_k": 33,
            "jaccard_threshold": 0.5,
            "health_check_interval": 45,
            "health_check_timeout": 30,
            "compensate_batch_size": 7,
        })
        assert r.status_code == 200
        saved = json.loads(Path(settings.config_file).read_text(encoding="utf-8"))
        assert saved["retrieval"] == {
            "max_graph_hops": 4, "rrf_k": 33, "jaccard_threshold": 0.5,
            "max_raw_content": settings.max_raw_content,
        }
        assert saved["health"]["health_check_interval"] == 45
        assert saved["health"]["health_check_timeout"] == 30
        assert saved["health"]["compensate_batch_size"] == 7
        # 运行时也立刻生效（无需重启）
        assert settings.max_graph_hops == 4 and settings.rrf_k == 33
        # 来源转为 file：界面据此显示「已落盘」
        assert test_app.get("/settings").json()["config_sources"]["rrf_k"] == "file"

    def test_put_new_tunables_persist(self, test_app):
        r = test_app.put("/settings", json={
            "max_raw_content": 12345,
            "agent_maintain_auto": False,
            "agent_maintain_max_nodes": 300,
            "agent_cmdmsg_max_rounds": 5,
            "agent_cr_skip_chars": 0,
            "log_retention_days": 3,
            "log_jsonl": True,
            "agent_logs_full": False,
            "wal_checkpoint_interval": 120,
            "wal_checkpoint_bytes": 4194304,
            "llm_structured_mode": "json",
        })
        assert r.status_code == 200
        saved = json.loads(Path(settings.config_file).read_text(encoding="utf-8"))
        assert saved["retrieval"]["max_raw_content"] == 12345
        assert saved["maintenance"]["agent_maintain_auto"] is False
        assert saved["maintenance"]["agent_maintain_max_nodes"] == 300
        assert saved["maintenance"]["agent_cmdmsg_max_rounds"] == 5
        assert saved["maintenance"]["agent_cr_skip_chars"] == 0
        assert saved["logs"] == {
            "log_retention_days": 3, "log_jsonl": True, "agent_logs_full": False,
        }
        assert saved["storage"]["wal_checkpoint_interval"] == 120
        assert saved["storage"]["wal_checkpoint_bytes"] == 4194304
        assert saved["agent"]["structured_mode"] == "json"
        assert settings.agent_maintain_auto is False
        assert settings.agent_cr_skip_chars == 0

    def test_put_retention_tunables_persist(self, test_app):
        """保留策略（v1.39）：两项新旋钮经 PUT 落盘并立即生效（0 = 关闭该项清理）。"""
        r = test_app.put("/settings", json={
            "graph_ops_retention": 1234,
            "trash_retention_days": 0,
        })
        assert r.status_code == 200
        saved = json.loads(Path(settings.config_file).read_text(encoding="utf-8"))
        assert saved["storage"]["graph_ops_retention"] == 1234
        assert saved["storage"]["trash_retention_days"] == 0
        assert settings.graph_ops_retention == 1234
        assert settings.trash_retention_days == 0
        data = test_app.get("/settings").json()
        assert data["graph_ops_retention"] == 1234
        assert data["trash_retention_days"] == 0

    def test_env_locked_field_reports_ignored(self, test_app, monkeypatch):
        """环境变量顶掉的项：**如实在响应里报出来**（不再静默无效）。"""
        monkeypatch.setenv("DPIM_RRF_K", "77")
        monkeypatch.setattr(
            settings, "_sources", {**settings.config_sources, "rrf_k": "env:DPIM_RRF_K"}
        )
        before = settings.rrf_k
        r = test_app.put("/settings", json={"rrf_k": 12})
        assert r.status_code == 200
        body = r.json()
        assert body["ignored_by_env"] == ["rrf_k(DPIM_RRF_K)"]
        assert "DPIM_RRF_K" in body["message"]
        assert settings.rrf_k == before  # 内存值按 env 重新读取后的值，绝不被 PUT 顶掉

    def test_validation_ranges_for_new_fields(self, test_app):
        assert test_app.put("/settings", json={"max_raw_content": 10}).status_code == 422
        assert test_app.put("/settings", json={"agent_cmdmsg_max_rounds": 99}).status_code == 422
        assert test_app.put("/settings", json={"wal_checkpoint_bytes": 1}).status_code == 422
        assert test_app.put("/settings", json={"log_retention_days": -1}).status_code == 422
        assert test_app.put("/settings", json={"llm_structured_mode": "yaml"}).status_code == 422
        assert test_app.put("/settings", json={"log_retention_days": 0}).status_code == 200
        # 保留策略（v1.39）：负数非法、上限外非法；0（关闭）与边界值合法
        assert test_app.put("/settings", json={"graph_ops_retention": -1}).status_code == 422
        assert test_app.put("/settings", json={"graph_ops_retention": 1_000_001}).status_code == 422
        assert test_app.put("/settings", json={"trash_retention_days": -1}).status_code == 422
        assert test_app.put("/settings", json={"trash_retention_days": 3651}).status_code == 422
        assert test_app.put("/settings", json={"graph_ops_retention": 0}).status_code == 200
        assert test_app.put("/settings", json={"trash_retention_days": 3650}).status_code == 200


class TestSecretScrubbing:
    """v1.46：错误原文**不得回显密钥**——httpx/h11 的报错会原样带上整条请求头值。

    实测（本项目 venv，活桩）：`api_key` 含换行时 `probe_models` 抛
    `LocalProtocolError: Illegal header value b'sk-abc\\nSECRETTAIL'`，明文密钥在异常文本里。
    这段原文会显示在卡片/概览台/顶栏，也会写进 `logs/backend-*.log`。
    """

    def test_sanitize_strips_control_chars(self):
        from core.security import sanitize_secret

        assert sanitize_secret("sk-abc\nSECRET") == "sk-abcSECRET"
        assert sanitize_secret("a\r\nb\tc") == "abc"
        assert sanitize_secret("") == ""

    def test_scrub_removes_raw_and_escaped_forms(self):
        from core.security import scrub_secrets

        key = "sk-abc\nSECRETTAIL"
        # 错误文本里是**转义形态**（字面反斜杠 + n），不是原文换行——两种都必须擦掉
        text = "LocalProtocolError: Illegal header value b'sk-abc\\nSECRETTAIL'"
        out = scrub_secrets(text, key)
        assert "SECRETTAIL" not in out
        assert "****" in out
        assert "SECRETTAIL" not in scrub_secrets("raw: " + key, key)

    def test_scrub_leaves_short_values_alone(self):
        from core.security import scrub_secrets

        # 过短的值不擦（否则会把正常文本打散）
        assert scrub_secrets("abc def", "abc") == "abc def"
        assert scrub_secrets("no secrets here") == "no secrets here"


# ─────────────── 模型探测（POST /settings/models，v1.34）───────────────────


class TestProviderModelsProbe:
    """探测端点：成功给列表，失败给**原文**（界面必须看得见失败原因）。

    v1.43 起探测按接口格式分流（`core.llm.probe_models`），故这里只验证
    「路由把哪些东西交给探测器」——三种格式的真实线上形状（头/路径/解析）
    由 `test_llm_formats.py` 用本地真 HTTP 服务器钉住。
    """

    def test_probe_existing_provider_uses_stored_key(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "https://api.siliconflow.cn/v1", "api_key": "sk-stored-123456"},
        })
        seen: dict[str, str] = {}

        async def _fake_probe(conf):
            seen.update(base_url=conf.base_url, api_key=conf.api_key, format=conf.format)
            return ["m1", "m2"]

        monkeypatch.setattr(settings_mod, "probe_models", _fake_probe)
        r = test_app.post("/settings/models", json={"provider": "sf"})
        assert r.status_code == 200
        assert r.json()["models"] == ["m1", "m2"]
        assert r.json()["error"] == ""
        # 留空 → 用已存密钥；格式缺省 → openai
        assert seen == {
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-stored-123456",
            "format": "openai",
        }

    def test_probe_new_entry_uses_submitted_values(self, test_app, monkeypatch):
        seen: dict[str, str] = {}

        async def _fake_probe(conf):
            seen.update(base_url=conf.base_url, api_key=conf.api_key, format=conf.format)
            return []

        monkeypatch.setattr(settings_mod, "probe_models", _fake_probe)
        r = test_app.post("/settings/models", json={
            "base_url": "http://localhost:5091/v1", "api_key": "sk-draft-999",
        })
        assert r.status_code == 200
        assert r.json()["models"] == []
        assert seen == {
            "base_url": "http://localhost:5091/v1",
            "api_key": "sk-draft-999",
            "format": "openai",
        }

    def test_probe_body_api_path_and_headers_win_over_stored(self, test_app, monkeypatch):
        """v1.45：`api_path` / `extra_headers` 与 base_url / api_key 同口径——**请求体优先**。

        修的是「草稿还没提交」这一类失败：前端卡片的「拉取模型」用草稿值探测，而后端配置里
        还没有这个条目（旧实现只发名字 → 一律「未填模型地址（base_url）」；自定义格式的条目
        还会因为缺额外请求头而 401）。
        """
        monkeypatch.setattr(settings, "providers", {
            "gw": {
                "base_url": "https://stored.local/v1",
                "api_key": "sk-stored",
                "api_path": "/stored/path",
                "extra_headers": {"X-Stored": "1"},
            },
        })
        seen: dict = {}

        async def _fake_probe(conf):
            seen.update(
                base_url=conf.base_url,
                api_path=conf.api_path,
                extra_headers=conf.extra_headers,
                format=conf.format,
            )
            return ["m1"]

        monkeypatch.setattr(settings_mod, "probe_models", _fake_probe)
        r = test_app.post("/settings/models", json={
            "provider": "gw",
            "base_url": "https://draft.local/v1",
            "api_path": "/draft/path",
            "extra_headers": {"X-Draft": "2"},
            "format": "custom",
        })
        assert r.status_code == 200
        assert seen == {
            "base_url": "https://draft.local/v1",
            "api_path": "/draft/path",
            "extra_headers": {"X-Draft": "2"},
            "format": "custom",
        }

    def test_probe_falls_back_to_stored_api_path_and_headers(self, test_app, monkeypatch):
        """只传 `provider` 名字时，api_path / extra_headers 仍从已存条目回落（零迁移）。"""
        monkeypatch.setattr(settings, "providers", {
            "gw": {
                "base_url": "https://stored.local/v1",
                "api_key": "sk-stored",
                "api_path": "/stored/path",
                "extra_headers": {"X-Stored": "1"},
            },
        })
        seen: dict = {}

        async def _fake_probe(conf):
            seen.update(api_path=conf.api_path, extra_headers=conf.extra_headers)
            return []

        monkeypatch.setattr(settings_mod, "probe_models", _fake_probe)
        r = test_app.post("/settings/models", json={"provider": "gw"})
        assert r.status_code == 200
        assert seen == {"api_path": "/stored/path", "extra_headers": {"X-Stored": "1"}}

    def test_probe_honours_requested_format(self, test_app, monkeypatch):
        """弹窗里刚选的格式必须传下去（否则选 Anthropic 仍按 Bearer 探测 → 必然 401）。"""
        monkeypatch.setattr(settings, "providers", {
            "claude": {"base_url": "https://api.anthropic.com/v1", "format": "anthropic"},
        })
        seen: dict[str, str] = {}

        async def _fake_probe(conf):
            seen["format"] = conf.format
            return ["claude-sonnet-4-5"]

        monkeypatch.setattr(settings_mod, "probe_models", _fake_probe)
        # 已登记条目的格式
        assert test_app.post("/settings/models", json={"provider": "claude"}).json()["models"]
        assert seen["format"] == "anthropic"
        # 未保存的新条目：以请求体里的格式为准
        test_app.post("/settings/models", json={
            "base_url": "https://gw.local/v1", "format": "custom",
        })
        assert seen["format"] == "custom"

    def test_probe_missing_base_url_reports_reason(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "providers", {})
        r = test_app.post("/settings/models", json={"provider": "nope"})
        assert r.status_code == 200
        assert "未填模型地址" in r.json()["error"]

    def test_probe_failure_returns_error_text(self, test_app, monkeypatch):
        """失败不抛 500：错误原文进 `error`（例如 401 / 连接被拒）。"""
        async def _boom(conf):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(settings_mod, "probe_models", _boom)
        r = test_app.post("/settings/models", json={"base_url": "http://127.0.0.1:1/v1"})
        assert r.status_code == 200
        assert "connection refused" in r.json()["error"]


# ─────────────────── 未配置态可见（/health 三态，v1.34）───────────────────


class TestUnconfiguredHealth:
    def test_health_unconfigured_when_no_provider(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "providers", {})
        monkeypatch.setattr(settings, "active_provider", "")
        data = test_app.get("/health").json()
        assert data["status"] == "unconfigured"  # 不是 degraded（没配 ≠ 连不上）
        assert data["ai_available"] is False
        assert "未配置任何 AI 提供商" in data["ai_unavailable_reason"]

    def test_health_degraded_when_configured_but_unreachable(self, test_app, monkeypatch):
        monkeypatch.setattr(settings, "providers", {
            "sf": {"base_url": "http://127.0.0.1:1/v1", "api_key": "k", "models": ["m"]},
        })
        monkeypatch.setattr(settings, "active_provider", "sf")
        monkeypatch.setattr(ai_state, "set_state", lambda available, reason="": None)
        monkeypatch.setattr(ai_state, "_available", False, raising=False)
        monkeypatch.setattr(
            ai_state, "_reason", "AI 连接失败（连续 3 次）：APIConnectionError", raising=False
        )
        data = test_app.get("/health").json()
        assert data["status"] == "degraded"
        assert "连接失败" in data["ai_unavailable_reason"]


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
        assert test_app.post("/ingest", json={"content": "x", "event_type": "interaction"}).status_code == 401
        assert test_app.put(
            "/settings", json={"active_provider": "attacker"},
            headers={"X-API-Key": "guess"},
        ).status_code == 401
        assert test_app.post(
            "/settings/models", json={"base_url": "http://attacker/v1"},
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
        resp = test_app.post("/ingest", json={"content": "a" * 1_000_000, "event_type": "interaction"})
        assert resp.status_code == 200

    def test_put_event_content_over_limit_rejected(self, test_app):
        eid = test_app.post("/ingest", json={"content": "seed", "event_type": "interaction"}).json()["event_id"]
        resp = test_app.put(f"/events/{eid}", json={"content": "x" * 1_000_001})
        assert resp.status_code == 422

    def test_query_max_hops_out_of_range(self, test_app):
        # v1.18：max_hops 允许 0（= 不扩散，事件原文/知识节点纯检索）；上界仍 5
        assert test_app.post("/query", json={"query": "x", "max_hops": 0}).status_code == 200
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
