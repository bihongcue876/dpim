
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
    assert s.max_raw_content == 200000  # 上下文护栏：600000 → 200000 字符
    assert s.compensate_check_interval == 5
    assert s.agent_maintain_auto is True  # 图维护自动触发默认开启
    assert s.agent_maintain_min_nodes == 10
    assert s.agent_maintain_max_nodes == 900  # 节点规模高水位触发（1000 软上限的 90%）
    assert s.agent_maintain_cooldown == 300  # 触发冷却（秒）


def test_env_override(monkeypatch):
    monkeypatch.setenv("DPIM_MEMORY_DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("DPIM_LLM_MODEL_NAME", "test-model")
    monkeypatch.setenv("DPIM_RRF_K", "100")
    monkeypatch.setenv("DPIM_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DPIM_MAX_RAW_CONTENT", "5000")
    monkeypatch.setenv("DPIM_HEALTH_CHECK_TIMEOUT", "30")
    monkeypatch.setenv("DPIM_AGENT_MAINTAIN_MAX_NODES", "500")
    monkeypatch.setenv("DPIM_AGENT_MAINTAIN_COOLDOWN", "120")
    s = Settings()
    assert s.memory_db_path == "/tmp/test.db"
    assert s.llm_model_name == "test-model"
    assert s.rrf_k == 100
    assert s.log_level == "DEBUG"
    assert s.max_raw_content == 5000
    assert s.health_check_timeout == 30
    assert s.agent_maintain_max_nodes == 500
    assert s.agent_maintain_cooldown == 120


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
