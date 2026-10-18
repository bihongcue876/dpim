
import json
import os
from pathlib import Path

import pytest

from core.config import Settings


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """隔离 dpim.json 与 DPIM_* 环境变量：默认值断言不能被开发机配置污染。

    v1.34 起 DPIM_LLM_BASE_URL 显式给出时会合成 `default` 提供商条目，
    所以这里连它一起清掉，否则「无默认」断言会被本机环境破坏。
    """
    monkeypatch.setenv("DPIM_CONFIG_FILE", str(tmp_path / "isolated_dpim.json"))
    for key in (
        "DPIM_LLM_BASE_URL",
        "DPIM_LLM_API_KEY",
        "DPIM_LLM_MODEL_NAME",
        "DPIM_LLM_TIMEOUT",
        "DPIM_LLM_MAX_TOKENS",
        "DPIM_LLM_ENABLE_THINKING",
        "DPIM_LLM_THINKING_BUDGET",
        "DPIM_PROVIDERS",
        "DPIM_ACTIVE_PROVIDER",
        "DPIM_ACTIVE_MODEL",
        # 本机 dpim/.env 会经 load_dotenv() 注入这几项（env 优先级高于 dpim.json）：
        # 断言必须与开发机的 .env 无关，否则「值来自 env 还是文件」根本测不准
        "DPIM_LOG_LEVEL",
        "DPIM_MEMORY_DB_PATH",
        "DPIM_GRAPH_JSON_PATH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_default_values(monkeypatch):
    """v1.34：**没有内置默认提供商**——未配置就是未配置（不再是 ollama + llama3:8b）。"""
    monkeypatch.delenv("DPIM_LLM_TIMEOUT", raising=False)
    monkeypatch.delenv("DPIM_HEALTH_CHECK_TIMEOUT", raising=False)
    s = Settings()
    assert s.memory_db_path == "./data/memory.db"
    assert s.graph_json_path == "./data/graph.json"
    assert s.providers == {}  # 一个提供商都没有
    assert s.active_provider == ""
    assert s.available_models() == []
    assert s.llm_configured is False
    assert "未配置任何 AI 提供商" in s.llm_config_error()
    assert s.llm_timeout == 666  # 调优默认（非身份）：本地模型宽容
    assert s.max_graph_hops == 2
    assert s.rrf_k == 60
    assert s.jaccard_threshold == 0.85
    assert s.health_check_interval == 60
    assert s.health_check_timeout == 120
    assert s.compensate_batch_size == 20
    assert s.log_level == "INFO"
    assert s.max_raw_content == 200000  # 上下文护栏：600000 → 200000 字符
    assert s.compensate_check_interval == 5
    assert s.agent_maintain_auto is True  # 图维护自动触发默认开启
    assert s.agent_maintain_min_nodes == 10
    assert s.agent_maintain_max_nodes == 200  # 节点规模高水位（此后每冷却周期都准备压缩）
    assert s.agent_maintain_cooldown == 60  # 触发冷却（秒）
    # 保留策略（v1.39）：graph_ops 表与 trash/ 目录的有界化
    assert s.graph_ops_retention == 5000  # 图层操作日志保留条数（压实，0 = 不压实）
    assert s.trash_retention_days == 30  # 回收站留档保留天数（0 = 永不清理）


# ── v1.36：前端可配置面 ────────────────────────────────────────────────────
# 读取链统一为 env（部署覆盖）→ dpim.json 段（前端持久化）→ 内置默认；
# `config_sources` 让界面看得见哪一项被环境变量顶掉（否则又是一次静默失败）。

_FILE_BACKED_ENV = (
    "DPIM_MAX_GRAPH_HOPS", "DPIM_RRF_K", "DPIM_JACCARD_THRESHOLD",
    "DPIM_MAX_RAW_CONTENT", "DPIM_HEALTH_CHECK_INTERVAL", "DPIM_COMPENSATE_CHECK_INTERVAL",
    "DPIM_AGENT_MAINTAIN_AUTO", "DPIM_AGENT_MAINTAIN_MAX_NODES", "DPIM_AGENT_CR_SKIP_CHARS",
    "DPIM_LOG_RETENTION_DAYS", "DPIM_LOG_JSONL", "DPIM_AGENT_LOGS_FULL",
    "DPIM_WAL_CHECKPOINT_INTERVAL", "DPIM_LLM_STRUCTURED_MODE",
)


def _clear_env(monkeypatch) -> None:
    for key in _FILE_BACKED_ENV:
        monkeypatch.delenv(key, raising=False)


def test_file_values_win_over_defaults_and_are_reported_as_file(monkeypatch):
    """dpim.json 各段的值生效，且来源标注为 `file`（前端落盘的东西重启后仍在）。"""
    _clear_env(monkeypatch)
    Path(os.environ["DPIM_CONFIG_FILE"]).write_text(
        json.dumps({
            "agent": {"structured_mode": "json"},
            "retrieval": {
                "max_graph_hops": 4, "rrf_k": 30, "jaccard_threshold": 0.5,
                "max_raw_content": 12345,
            },
            "health": {"health_check_interval": 30, "compensate_check_interval": 7},
            "maintenance": {
                "agent_maintain_auto": False, "agent_maintain_max_nodes": 555,
                "agent_cr_skip_chars": 0,
            },
            "logs": {"log_retention_days": 3, "log_jsonl": True, "agent_logs_full": False},
            "storage": {"wal_checkpoint_interval": 77,
                        "graph_ops_retention": 1234, "trash_retention_days": 7},
        }),
        encoding="utf-8",
    )
    s = Settings()
    assert (s.max_graph_hops, s.rrf_k) == (4, 30)
    assert (s.jaccard_threshold, s.max_raw_content) == (0.5, 12345)
    assert (s.health_check_interval, s.compensate_check_interval) == (30, 7)
    assert s.agent_maintain_auto is False and s.agent_maintain_max_nodes == 555
    assert s.agent_cr_skip_chars == 0  # 0 是合法值，不能被 falsy 判断吞掉
    assert s.log_retention_days == 3 and s.log_jsonl is True and s.agent_logs_full is False
    assert s.wal_checkpoint_interval == 77
    assert (s.graph_ops_retention, s.trash_retention_days) == (1234, 7)
    assert s.llm_structured_mode == "json"
    assert s.config_sources["max_graph_hops"] == "file"
    assert s.config_sources["agent_logs_full"] == "file"
    assert s.config_sources["log_level"] == "default"  # 该文件没写顶层 log_level
    assert s.config_sources["providers"] == "default"


def test_env_beats_file_and_is_reported_as_locked(monkeypatch):
    """环境变量优先于文件，来源标成 `env:DPIM_X` —— 界面据此提示「改了不生效」。"""
    _clear_env(monkeypatch)
    Path(os.environ["DPIM_CONFIG_FILE"]).write_text(
        json.dumps({"retrieval": {"rrf_k": 30}}), encoding="utf-8"
    )
    monkeypatch.setenv("DPIM_RRF_K", "99")
    s = Settings()
    assert s.rrf_k == 99
    assert s.config_sources["rrf_k"] == "env:DPIM_RRF_K"


def test_save_writes_every_section(monkeypatch):
    """`save_dpim_config()` 必须把所有前端可改项落盘（此前 6 项只在内存生效）。"""
    _clear_env(monkeypatch)
    s = Settings()
    s.max_graph_hops = 3
    s.max_raw_content = 4096
    s.agent_maintain_auto = False
    s.agent_maintain_cooldown = 11
    s.log_jsonl = True
    s.agent_logs_full = False
    s.wal_checkpoint_interval = 22
    s.graph_ops_retention = 777
    s.trash_retention_days = 0
    s.llm_structured_mode = "tools"
    s.save_dpim_config()
    data = json.loads(Path(s.config_file).read_text(encoding="utf-8"))
    assert data["retrieval"]["max_graph_hops"] == 3
    assert data["retrieval"]["max_raw_content"] == 4096
    assert data["maintenance"]["agent_maintain_auto"] is False
    assert data["maintenance"]["agent_maintain_cooldown"] == 11
    assert data["logs"]["log_jsonl"] is True
    assert data["logs"]["agent_logs_full"] is False
    assert data["storage"]["wal_checkpoint_interval"] == 22
    assert data["storage"]["graph_ops_retention"] == 777
    assert data["storage"]["trash_retention_days"] == 0  # 0 = 关闭清理，是合法值
    assert data["agent"]["structured_mode"] == "tools"
    # 重新加载：值真的从文件回来了（重启不丢）
    again = Settings()
    assert again.max_graph_hops == 3
    assert again.agent_maintain_auto is False
    assert again.log_jsonl is True
    assert again.wal_checkpoint_interval == 22
    assert (again.graph_ops_retention, again.trash_retention_days) == (777, 0)
    assert again.llm_structured_mode == "tools"


def test_invalid_file_value_falls_back_to_default(monkeypatch):
    """文件里写了非法值：回退默认并标注 default（不炸、不静默用错值）。"""
    _clear_env(monkeypatch)
    Path(os.environ["DPIM_CONFIG_FILE"]).write_text(
        json.dumps({"retrieval": {"rrf_k": "not-a-number"}}), encoding="utf-8"
    )
    s = Settings()
    assert s.rrf_k == 60
    assert s.config_sources["rrf_k"] == "default"


def test_unconfigured_reasons(monkeypatch):

    """未配置原因必须**可区分、可展示**（三种：没有提供商 / 名字不在注册表 / 缺地址或模型）。"""
    monkeypatch.setenv(
        "DPIM_PROVIDERS", '{"sf": {"base_url": "", "api_key": "k", "models": ["m"]}}'
    )
    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", "sf")
    s = Settings()
    assert "未填模型地址" in s.llm_config_error()

    monkeypatch.setenv("DPIM_PROVIDERS", '{"sf": {"base_url": "http://x/v1", "api_key": "k"}}')
    s = Settings()
    assert "未登记任何模型" in s.llm_config_error()

    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", "gone")
    s = Settings()
    assert "未登记" in s.llm_config_error() and "gone" in s.llm_config_error()
    assert s.llm_configured is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("DPIM_MEMORY_DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("DPIM_RRF_K", "100")
    monkeypatch.setenv("DPIM_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DPIM_MAX_RAW_CONTENT", "5000")
    monkeypatch.setenv("DPIM_HEALTH_CHECK_TIMEOUT", "30")
    monkeypatch.setenv("DPIM_AGENT_MAINTAIN_MAX_NODES", "500")
    monkeypatch.setenv("DPIM_AGENT_MAINTAIN_COOLDOWN", "120")
    s = Settings()
    assert s.memory_db_path == "/tmp/test.db"
    assert s.rrf_k == 100
    assert s.log_level == "DEBUG"
    assert s.max_raw_content == 5000
    assert s.health_check_timeout == 30
    assert s.agent_maintain_max_nodes == 500
    assert s.agent_maintain_cooldown == 120


def test_env_seeds_default_provider_only_when_explicit(monkeypatch):
    """纯环境变量部署：显式给 DPIM_LLM_BASE_URL → 合成 `default` 条目；只给模型名不合成。"""
    monkeypatch.setenv("DPIM_LLM_MODEL_NAME", "only-model")  # 只有模型名，没有地址
    s = Settings()
    assert s.providers == {}  # 不合成（不再有写死地址）
    assert s.llm_configured is False

    monkeypatch.setenv("DPIM_LLM_BASE_URL", "http://env-host:9999/v1")
    monkeypatch.setenv("DPIM_LLM_API_KEY", "sk-env")
    s = Settings()
    assert list(s.providers) == ["default"]
    assert s.active_provider == "default"  # 注册表首个自动成为活动
    assert s.available_models() == ["only-model"]
    assert s.provider_config().base_url == "http://env-host:9999/v1"
    assert s.provider_config().api_key == "sk-env"
    assert s.llm_configured is True


def test_provider_multi_models_and_active_model(monkeypatch):
    monkeypatch.setenv(
        "DPIM_PROVIDERS",
        '{"qwen": {"base_url": "http://localhost:5091/v1", "api_key": "1",'
        ' "models": ["Qwen3.5-9B", "Qwen3.5-35B-A3B"]}}',
    )
    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", "qwen")
    monkeypatch.setenv("DPIM_ACTIVE_MODEL", "Qwen3.5-35B-A3B")
    s = Settings()
    assert s.available_models() == ["Qwen3.5-9B", "Qwen3.5-35B-A3B"]
    assert s.role_model("cr") == "Qwen3.5-35B-A3B"  # active_model 优先
    assert s.provider_config().base_url == "http://localhost:5091/v1"


def test_provider_named_primary_is_plain_key(monkeypatch):
    """v1.34：`primary` 不再特殊——它就是一个普通注册表键名（旧语义已删除）。"""
    monkeypatch.setenv(
        "DPIM_PROVIDERS",
        '{"primary": {"base_url": "http://localhost:6000/v1", "api_key": "x", "model": "m"}}',
    )
    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", "primary")
    s = Settings()
    assert s.provider_config().base_url == "http://localhost:6000/v1"
    assert s.role_model("cr") == "m"
    # 删掉这条登记后就是「未配置」，不会回退到任何内置主配置
    s.providers = {}
    assert s.llm_configured is False
    assert s.provider_config().base_url == ""


def test_vendor_defaults(monkeypatch):
    monkeypatch.delenv("DPIM_LLM_MAX_TOKENS", raising=False)
    monkeypatch.delenv("DPIM_LLM_ENABLE_THINKING", raising=False)
    monkeypatch.delenv("DPIM_LLM_THINKING_BUDGET", raising=False)
    s = Settings()
    assert s.llm_max_tokens is None
    assert s.llm_enable_thinking is None
    assert s.llm_thinking_budget is None


def test_vendor_env_override(monkeypatch):
    monkeypatch.setenv("DPIM_LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("DPIM_LLM_ENABLE_THINKING", "true")
    monkeypatch.setenv("DPIM_LLM_THINKING_BUDGET", "2048")
    s = Settings()
    assert s.llm_max_tokens == 4096
    assert s.llm_enable_thinking is True
    assert s.llm_thinking_budget == 2048


def test_provider_entry_vendor_fields(monkeypatch):
    monkeypatch.setenv(
        "DPIM_PROVIDERS",
        '{"sf": {"base_url": "https://api.siliconflow.cn/v1", "api_key": "k",'
        ' "models": ["m1"], "max_tokens": 8192, "enable_thinking": false,'
        ' "thinking_budget": 1024, "thinking_style": "top_level",'
        ' "extra_body": {"reasoning_effort": "high"}, "structured_mode": "tools"}}',
    )
    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", "sf")
    s = Settings()
    conf = s.provider_config()
    assert conf.max_tokens == 8192
    assert conf.enable_thinking is False
    assert conf.thinking_budget == 1024
    assert conf.thinking_style == "top_level"
    assert conf.extra_body == {"reasoning_effort": "high"}
    assert conf.structured_mode == "tools"
    assert conf.timeout == s.llm_timeout  # 未显式声明 timeout → 回退全局
    assert s.role_provider("cr").max_tokens == 8192  # 角色透传厂商参数


def test_storage_paths_roundtrip_via_dpim_json(monkeypatch, tmp_path):
    """v1.16：存储路径/日志级别持久化 dpim.json — save 后新实例读回，重启保留语义。"""
    cfg_file = tmp_path / "dpim.json"
    monkeypatch.setenv("DPIM_CONFIG_FILE", str(cfg_file))
    monkeypatch.delenv("DPIM_MEMORY_DB_PATH", raising=False)
    monkeypatch.delenv("DPIM_GRAPH_JSON_PATH", raising=False)
    monkeypatch.delenv("DPIM_LOG_LEVEL", raising=False)
    s = Settings()
    assert s.memory_db_path == "./data/memory.db"  # 无 storage 段 → 内置默认

    s.memory_db_path = str(tmp_path / "mem.db")
    s.graph_json_path = str(tmp_path / "graph.json")
    s.log_level = "DEBUG"
    s.save_dpim_config()

    s2 = Settings()  # 模拟重启
    assert s2.memory_db_path == str(tmp_path / "mem.db")
    assert s2.graph_json_path == str(tmp_path / "graph.json")
    assert s2.log_level == "DEBUG"


def test_storage_paths_env_overrides_dpim_json(monkeypatch, tmp_path):
    """env 显式设置压制 dpim.json（部署覆盖语义，与 providers 行为一致）。"""
    cfg_file = tmp_path / "dpim.json"
    monkeypatch.setenv("DPIM_CONFIG_FILE", str(cfg_file))
    monkeypatch.setenv("DPIM_MEMORY_DB_PATH", "/env/override.db")
    monkeypatch.delenv("DPIM_LOG_LEVEL", raising=False)
    s = Settings()
    s.memory_db_path = "/json/path.db"
    s.log_level = "DEBUG"
    s.save_dpim_config()

    s2 = Settings()
    assert s2.memory_db_path == "/env/override.db"  # env 胜出
    assert s2.log_level == "DEBUG"  # 未设 env → dpim.json 生效


def test_provider_registry_roundtrip_via_dpim_json(monkeypatch, tmp_path):
    """v1.34：BYOK 注册表整体落盘 —— save 后新实例读回，重启保留。

    一条提供商记录即全部身份（名称 / 地址 / 密钥 / 模型列表 / 厂商适配），
    不再有独立的「主配置」段需要单独持久化。
    """
    cfg_file = tmp_path / "dpim.json"
    monkeypatch.setenv("DPIM_CONFIG_FILE", str(cfg_file))
    s = Settings()
    assert s.providers == {}  # 空配置：没有 AI，也没有假默认

    s.providers = {
        "siliconflow": {
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-real-key-123456",
            "models": ["deepseek-ai/DeepSeek-V4-Flash", "Qwen/Qwen3.5-4B"],
            "max_tokens": 8192,
            "thinking_style": "top_level",
        }
    }
    s.active_provider = "siliconflow"
    s.active_model = "deepseek-ai/DeepSeek-V4-Flash"
    s.save_dpim_config()

    data = json.loads(Path(cfg_file).read_text(encoding="utf-8"))
    assert data["providers"]["siliconflow"]["api_key"] == "sk-real-key-123456"
    assert "llm" not in data  # v1.34：不再有 llm 段（身份只在 providers 里）

    s2 = Settings()  # 模拟重启
    assert list(s2.providers) == ["siliconflow"]
    assert s2.active_provider == "siliconflow"
    assert s2.available_models() == ["deepseek-ai/DeepSeek-V4-Flash", "Qwen/Qwen3.5-4B"]
    assert s2.provider_config().model == "deepseek-ai/DeepSeek-V4-Flash"
    assert s2.provider_config().api_key == "sk-real-key-123456"
    assert s2.llm_configured is True


def test_providers_env_overrides_dpim_json(monkeypatch, tmp_path):
    """env 部署覆盖语义：DPIM_PROVIDERS 显式设置压制 dpim.json 的 providers 段。"""
    cfg_file = tmp_path / "dpim.json"
    monkeypatch.setenv("DPIM_CONFIG_FILE", str(cfg_file))
    s = Settings()
    s.providers = {"json-p": {"base_url": "https://json.example/v1", "models": ["json-model"]}}
    s.active_provider = "json-p"
    s.save_dpim_config()

    monkeypatch.setenv(
        "DPIM_PROVIDERS",
        '{"env-p": {"base_url": "https://env.example/v1", "models": ["env-model"]}}',
    )
    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", "env-p")
    s2 = Settings()
    assert list(s2.providers) == ["env-p"]  # env 胜出
    assert s2.available_models() == ["env-model"]
    assert s2.provider_config().base_url == "https://env.example/v1"


# ── 接口格式（v1.43）：provider 条目的第五个维度 ─────────────────────────


def _with_providers(monkeypatch, tmp_path, providers: dict) -> Settings:
    """用 DPIM_PROVIDERS 造一个带指定条目的 Settings（env 优先级最高，绕开文件）。"""
    monkeypatch.setenv("DPIM_CONFIG_FILE", str(tmp_path / "fmt_dpim.json"))
    monkeypatch.setenv("DPIM_PROVIDERS", json.dumps(providers, ensure_ascii=False))
    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", next(iter(providers)))
    return Settings()


def test_format_defaults_to_openai(monkeypatch, tmp_path):
    """老条目没有 format 键 → openai（与从前行为完全一致，零迁移）。"""
    s = _with_providers(monkeypatch, tmp_path, {
        "p": {"base_url": "https://x.example/v1", "models": ["m"]},
    })
    conf = s.provider_config()
    assert conf.format == "openai"
    assert conf.api_path == ""
    assert conf.extra_headers is None


def test_format_and_custom_fields_parsed(monkeypatch, tmp_path):
    s = _with_providers(monkeypatch, tmp_path, {
        "p": {
            "base_url": "https://gw.example/v1", "models": ["m"],
            "format": "custom", "api_path": "chat/x",     # 故意不写前导斜杠
            "extra_headers": {"X-K": "v", "N": 7},        # 值统一成字符串
        },
    })
    conf = s.provider_config()
    assert conf.format == "custom"
    assert conf.api_path == "chat/x"
    assert conf.extra_headers == {"X-K": "v", "N": "7"}


def test_unknown_format_falls_back_to_openai(monkeypatch, tmp_path):
    """未知格式不静默变成「不工作」：归一为 openai（并告警），条目仍可用。"""
    s = _with_providers(monkeypatch, tmp_path, {
        "p": {"base_url": "https://x.example/v1", "models": ["m"], "format": "grpc"},
    })
    assert s.provider_config().format == "openai"


def test_role_provider_carries_format(monkeypatch, tmp_path):
    """按角色的 ProviderConfig 也必须带上格式——否则四个 Agent 会走错协议。"""
    s = _with_providers(monkeypatch, tmp_path, {
        "p": {
            "base_url": "https://api.anthropic.com/v1", "models": ["claude-sonnet-4-5"],
            "format": "anthropic", "extra_headers": {"X-Tenant": "dpim"},
        },
    })
    conf = s.role_provider("gr")
    assert conf.format == "anthropic"
    assert conf.model == "claude-sonnet-4-5"
    assert conf.extra_headers == {"X-Tenant": "dpim"}


def test_format_persists_to_dpim_json(monkeypatch, tmp_path):
    """落盘 → 重读闭环：格式三件套必须活过重启（否则又是「改了没效果」）。"""
    path = tmp_path / "fmt_dpim.json"
    monkeypatch.setenv("DPIM_CONFIG_FILE", str(path))
    monkeypatch.delenv("DPIM_PROVIDERS", raising=False)
    s = Settings()
    s.providers = {
        "gw": {
            "base_url": "https://gw.example/v1", "api_key": "", "models": ["m"],
            "format": "responses", "api_path": "/responses",
            "extra_headers": {"X-K": "v"},
        },
    }
    s.active_provider = "gw"
    s.save_dpim_config()

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["providers"]["gw"]["format"] == "responses"
    assert saved["providers"]["gw"]["api_path"] == "/responses"
    assert saved["providers"]["gw"]["extra_headers"] == {"X-K": "v"}

    again = Settings()
    conf = again.provider_config("gw")
    assert conf.format == "responses"
    assert conf.api_path == "/responses"
    assert conf.extra_headers == {"X-K": "v"}
