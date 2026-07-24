
from core.config import Settings


def test_default_values():
    s = Settings()
    assert s.memory_db_path == "./data/memory.db"
    assert s.graph_json_path == "./data/graph.json"
    assert s.llm_base_url == "http://localhost:11434/v1"
    assert s.llm_model_name == "llama3:8b"
    assert s.llm_timeout == 30
    assert s.max_graph_hops == 2
    assert s.rrf_k == 60
    assert s.jaccard_threshold == 0.85
    assert s.health_check_interval == 60
    assert s.compensate_batch_size == 20
    assert s.log_level == "INFO"


def test_env_override(monkeypatch):
    monkeypatch.setenv("DPIM_MEMORY_DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("DPIM_LLM_MODEL_NAME", "test-model")
    monkeypatch.setenv("DPIM_RRF_K", "100")
    monkeypatch.setenv("DPIM_LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.memory_db_path == "/tmp/test.db"
    assert s.llm_model_name == "test-model"
    assert s.rrf_k == 100
    assert s.log_level == "DEBUG"
