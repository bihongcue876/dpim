"""应用配置，环境变量驱动（支持 .env 文件）"""

from os import getenv

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self):
        self.memory_db_path = getenv("DPIM_MEMORY_DB_PATH", "./data/memory.db")
        self.graph_json_path = getenv("DPIM_GRAPH_JSON_PATH", "./data/graph.json")
        self.llm_base_url = getenv("DPIM_LLM_BASE_URL", "http://localhost:11434/v1")
        self.llm_api_key = getenv("DPIM_LLM_API_KEY", "")
        self.llm_model_name = getenv("DPIM_LLM_MODEL_NAME", "llama3:8b")
        self.llm_timeout = int(getenv("DPIM_LLM_TIMEOUT", "30"))
        self.max_graph_hops = int(getenv("DPIM_MAX_GRAPH_HOPS", "2"))
        self.rrf_k = int(getenv("DPIM_RRF_K", "60"))
        self.jaccard_threshold = float(getenv("DPIM_JACCARD_THRESHOLD", "0.85"))
        self.health_check_interval = int(getenv("DPIM_HEALTH_CHECK_INTERVAL", "60"))
        self.compensate_batch_size = int(getenv("DPIM_COMPENSATE_BATCH_SIZE", "20"))
        self.log_level = getenv("DPIM_LOG_LEVEL", "INFO")


settings = Settings()
