"""应用配置，环境变量驱动（支持 .env 文件）"""

import json
import logging
import warnings
from dataclasses import dataclass
from os import getenv
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """一个 LLM 提供商实例：OpenAI 兼容协议。"""

    name: str
    base_url: str
    api_key: str
    model: str
    timeout: int


# Agent 角色
ROLES = ("cr", "in", "gr", "meta")


class Settings:
    def __init__(self) -> None:
        self.memory_db_path = getenv("DPIM_MEMORY_DB_PATH", "./data/memory.db")
        self.graph_json_path = getenv("DPIM_GRAPH_JSON_PATH", "./data/graph.json")
        # ── 主 provider（向后兼容，DPIM_LLM_*）──
        self.llm_base_url = getenv("DPIM_LLM_BASE_URL", "http://localhost:11434/v1")
        self.llm_api_key = getenv("DPIM_LLM_API_KEY", "")
        self.llm_model_name = getenv("DPIM_LLM_MODEL_NAME", "llama3:8b")
        self.llm_timeout = int(getenv("DPIM_LLM_TIMEOUT", "30"))
        # ── BYOK 多提供商注册（DPIM_PROVIDERS: JSON dict）──
        self.providers: dict[str, dict[str, Any]] = {}
        raw_providers = getenv("DPIM_PROVIDERS", "").strip()
        if raw_providers:
            try:
                parsed = json.loads(raw_providers)
                if isinstance(parsed, dict):
                    self.providers = parsed
                else:
                    warnings.warn("DPIM_PROVIDERS 应为 JSON 对象 {name: {...}}", stacklevel=2)
            except json.JSONDecodeError:
                warnings.warn("DPIM_PROVIDERS 解析失败，已忽略", stacklevel=2)
        self.active_provider = getenv("DPIM_ACTIVE_PROVIDER", "primary")
        # ── Agent 管线开关 ──
        self.agent_mode = getenv("DPIM_AGENT_MODE", "disabled")  # disabled | pipeline
        self.agent_max_retries = int(getenv("DPIM_AGENT_MAX_RETRIES", "2"))
        # ── 角色模型路由（空值 → 回退活动 provider 默认模型）──
        self.agent_cr_model = getenv("DPIM_AGENT_CR_MODEL", "")
        self.agent_in_model = getenv("DPIM_AGENT_IN_MODEL", "")
        self.agent_gr_model = getenv("DPIM_AGENT_GR_MODEL", "")
        self.agent_meta_model = getenv("DPIM_AGENT_META_MODEL", "")
        self.max_graph_hops = int(getenv("DPIM_MAX_GRAPH_HOPS", "2"))
        self.rrf_k = int(getenv("DPIM_RRF_K", "60"))
        self.jaccard_threshold = float(getenv("DPIM_JACCARD_THRESHOLD", "0.85"))
        self.health_check_interval = int(getenv("DPIM_HEALTH_CHECK_INTERVAL", "60"))
        self.compensate_batch_size = int(getenv("DPIM_COMPENSATE_BATCH_SIZE", "20"))
        self.log_level = getenv("DPIM_LOG_LEVEL", "INFO")
        self._validate()

    def _validate(self) -> None:
        """启动时校验关键配置项，尽早暴露问题。"""
        parsed = urlparse(self.llm_base_url)
        if not parsed.scheme or not parsed.netloc:
            warnings.warn(
                f"DPIM_LLM_BASE_URL='{self.llm_base_url}' 格式无效，"
                "应为 http://host:port/v1 格式",
                stacklevel=2,
            )
        if not self.llm_api_key:
            logger.warning(
                "DPIM_LLM_API_KEY 为空。Ollama 本地部署无需此值，"
                "远程服务（OpenAI 等）需设置 API Key"
            )
        if self.agent_mode not in ("disabled", "pipeline"):
            warnings.warn(
                f"DPIM_AGENT_MODE='{self.agent_mode}' 非法，应为 disabled | pipeline",
                stacklevel=2,
            )

    def provider_config(self, provider_name: str | None = None) -> ProviderConfig:
        """解析一个 provider 的配置；未注册或 'primary' → 主 provider（DPIM_LLM_*）。"""
        name = provider_name or self.active_provider
        if name != "primary" and name in self.providers:
            p = self.providers[name]
            return ProviderConfig(
                name=name,
                base_url=str(p.get("base_url", "")),
                api_key=str(p.get("api_key", "")),
                model=str(p.get("model", "")),
                timeout=int(p.get("timeout", self.llm_timeout)),
            )
        return ProviderConfig(
            name="primary",
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            model=self.llm_model_name,
            timeout=self.llm_timeout,
        )

    def role_model(self, role: str) -> str:
        """角色 → 模型名：角色显式指定则优先，否则用活动 provider 默认模型。"""
        override = getattr(self, f"agent_{role}_model", "") or ""
        return override if override else self.provider_config().model

    def role_provider(self, role: str) -> ProviderConfig:
        """角色 → ProviderConfig：base_url/api_key 取活动 provider，model 按角色解析。"""
        conf = self.provider_config()
        return ProviderConfig(
            name=conf.name,
            base_url=conf.base_url,
            api_key=conf.api_key,
            model=self.role_model(role),
            timeout=conf.timeout,
        )


settings = Settings()
