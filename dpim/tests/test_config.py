
from core.config import Settings


def test_default_values(monkeypatch):
    monkeypatch.delenv("DPIM_LLM_TIMEOUT", raising=False)
    monkeypatch.delenv("DPIM_HEALTH_CHECK_TIMEOUT", raising=False)
    s = Settings()
    assert s.memory_db_path == "./data/memory.db"
    assert s.graph_json_path == "./data/graph.json"
    assert s.llm_base_url == "http://localhost:11434/v1"
    assert s.llm_model_name == "llama3:8b"
    assert s.llm_timeout == 666  # 本地模型宽容默认
    assert s.max_graph_hops == 2
    assert s.rrf_k == 60
    assert s.jaccard_threshold == 0.85
    assert s.health_check_interval == 60
    assert s.health_check_timeout == 120
    assert s.compensate_batch_size == 20
    assert s.log_level == "INFO"
    assert s.max_raw_content == 600000


def test_env_override(monkeypatch):
    monkeypatch.setenv("DPIM_MEMORY_DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("DPIM_LLM_MODEL_NAME", "test-model")
    monkeypatch.setenv("DPIM_RRF_K", "100")
    monkeypatch.setenv("DPIM_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DPIM_MAX_RAW_CONTENT", "5000")
    monkeypatch.setenv("DPIM_HEALTH_CHECK_TIMEOUT", "30")
    s = Settings()
    assert s.memory_db_path == "/tmp/test.db"
    assert s.llm_model_name == "test-model"
    assert s.rrf_k == 100
    assert s.log_level == "DEBUG"
    assert s.max_raw_content == 5000
    assert s.health_check_timeout == 30


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


def test_provider_registry_primary_override(monkeypatch):
    monkeypatch.setenv(
        "DPIM_PROVIDERS",
        '{"primary": {"base_url": "http://localhost:6000/v1", "api_key": "x", "model": "m"}}',
    )
    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", "primary")
    s = Settings()
    assert s.provider_config().base_url == "http://localhost:6000/v1"
    assert s.role_model("cr") == "m"


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
