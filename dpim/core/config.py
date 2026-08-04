"""应用配置，环境变量驱动（支持 .env 文件）+ dpim.json 结构化配置"""

import json
import logging
import os
import warnings
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """一个 LLM 提供商实例：OpenAI 兼容协议 + 厂商适配参数。

    - max_tokens：输出 token 上限（None = 不传，用服务端默认）
    - enable_thinking：思考开关（None = 不干预，用服务端默认）
    - thinking_budget：思考 token 预算（None = 不传）
    - thinking_style：思考参数的载体：top_level（SiliconFlow/DeepSeek 顶层字段）
      | chat_template_kwargs（llama.cpp）| auto（本地地址自动选 chat_template_kwargs）
    - extra_body：任意厂商参数透传（如 DeepSeek 的 reasoning_effort 等）
    - structured_mode：结构化输出模式覆盖（md_json | json | tools，空 = 用全局）
    """

    name: str
    base_url: str
    api_key: str
    model: str
    timeout: int
    max_tokens: int | None = None
    enable_thinking: bool | None = None
    thinking_budget: int | None = None
    thinking_style: str = "auto"
    extra_body: dict | None = None
    structured_mode: str | None = None


def _parse_bool_or_none(raw: str) -> bool | None:
    """env 布尔解析：true/1/yes → True，false/0/no → False，其余（含空）→ None。"""
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


# Agent 角色
ROLES = ("cr", "in", "gr", "meta")


class Settings:
    def __init__(self) -> None:
        # ── dpim.json 结构化配置（BYOK/Agent；env DPIM_* 优先于文件）──
        self.config_file = getenv(
            "DPIM_CONFIG_FILE",
            str(Path(__file__).resolve().parent.parent / "dpim.json"),
        )
        cfg = self._read_dpim_config()
        agent_cfg = cfg.get("agent", {}) if isinstance(cfg, dict) else {}
        self.memory_db_path = getenv("DPIM_MEMORY_DB_PATH", "./data/memory.db")
        self.graph_json_path = getenv("DPIM_GRAPH_JSON_PATH", "./data/graph.json")
        # ── 主 provider（向后兼容，DPIM_LLM_*）──
        self.llm_base_url = getenv("DPIM_LLM_BASE_URL", "http://localhost:11434/v1")
        self.llm_api_key = getenv("DPIM_LLM_API_KEY", "")
        self.llm_model_name = getenv("DPIM_LLM_MODEL_NAME", "llama3:8b")
        # 生成请求超时（秒）：本地模型慢，默认放宽到 300；provider 条目可单独覆盖
        self.llm_timeout = int(getenv("DPIM_LLM_TIMEOUT", "300"))
        # ── 厂商适配全局默认（provider 条目可单独覆盖）──
        # 输出 token 上限（0 = 不传，用服务端默认）
        self.llm_max_tokens = int(getenv("DPIM_LLM_MAX_TOKENS", "0")) or None
        # 思考开关（空 = 不干预；SiliconFlow 顶层 enable_thinking / llama.cpp chat_template_kwargs）
        self.llm_enable_thinking = _parse_bool_or_none(getenv("DPIM_LLM_ENABLE_THINKING", ""))
        # 思考 token 预算（0 = 不传）
        self.llm_thinking_budget = int(getenv("DPIM_LLM_THINKING_BUDGET", "0")) or None
        # ── BYOK 多提供商注册：env DPIM_PROVIDERS 优先，否则读 dpim.json ──
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
        elif isinstance(cfg.get("providers"), dict):
            self.providers = cfg["providers"]
        self.active_provider = getenv("DPIM_ACTIVE_PROVIDER", cfg.get("active_provider", "primary"))
        # ── Agent 管线开关 ──
        self.agent_mode = getenv("DPIM_AGENT_MODE", str(agent_cfg.get("mode", "disabled")))
        self.agent_max_retries = int(
            getenv("DPIM_AGENT_MAX_RETRIES", str(agent_cfg.get("max_retries", "2")))
        )
        # ── 上下文护栏：单次 LLM 输入中 raw_content 最大字符数（超限截断）──
        self.max_raw_content = int(getenv("DPIM_MAX_RAW_CONTENT", "10000"))
        # ── 结构化输出模式：md_json（默认，兼容 llama.cpp）| json | tools ──
        self.llm_structured_mode = getenv("DPIM_LLM_STRUCTURED_MODE", "md_json")
        # ── 角色模型路由（空值 → 回退活动 provider 默认模型）──
        self.agent_cr_model = getenv("DPIM_AGENT_CR_MODEL", str(agent_cfg.get("cr_model", "")))
        self.agent_in_model = getenv("DPIM_AGENT_IN_MODEL", str(agent_cfg.get("in_model", "")))
        self.agent_gr_model = getenv("DPIM_AGENT_GR_MODEL", str(agent_cfg.get("gr_model", "")))
        self.agent_meta_model = getenv(
            "DPIM_AGENT_META_MODEL", str(agent_cfg.get("meta_model", ""))
        )
        # ── 使用中的模型（活动 provider 的默认选用模型，空 → provider 首个/默认）──
        self.active_model = getenv("DPIM_ACTIVE_MODEL", cfg.get("active_model", ""))
        self.max_graph_hops = int(getenv("DPIM_MAX_GRAPH_HOPS", "2"))
        self.rrf_k = int(getenv("DPIM_RRF_K", "60"))
        self.jaccard_threshold = float(getenv("DPIM_JACCARD_THRESHOLD", "0.85"))
        self.health_check_interval = int(getenv("DPIM_HEALTH_CHECK_INTERVAL", "60"))
        # 健康检查超时（秒）：与生成超时分离，模型加载/单槽忙碌时不至于 3 连败假降级
        self.health_check_timeout = int(getenv("DPIM_HEALTH_CHECK_TIMEOUT", "60"))
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
        if self.agent_mode not in ("disabled", "pipeline"):
            warnings.warn(
                f"DPIM_AGENT_MODE='{self.agent_mode}' 非法，应为 disabled | pipeline",
                stacklevel=2,
            )
        if self.llm_structured_mode not in ("md_json", "json", "tools"):
            warnings.warn(
                f"DPIM_LLM_STRUCTURED_MODE='{self.llm_structured_mode}' 非法，"
                "应为 md_json | json | tools",
                stacklevel=2,
            )

    def _read_dpim_config(self) -> dict[str, Any]:
        """读取 dpim.json 结构化配置（BYOK/Agent）。文件不存在或损坏返回 {}。"""
        path = Path(self.config_file)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("dpim.json 解析失败，已忽略: %s", path)
            return {}

    def save_dpim_config(self) -> None:
        """把当前 BYOK/Agent 配置持久化到 dpim.json（前端改配置后调用）。"""
        payload = {
            "active_provider": self.active_provider,
            "active_model": self.active_model,
            "providers": self.providers,
            "agent": {
                "mode": self.agent_mode,
                "max_retries": self.agent_max_retries,
                "cr_model": self.agent_cr_model,
                "in_model": self.agent_in_model,
                "gr_model": self.agent_gr_model,
                "meta_model": self.agent_meta_model,
            },
        }
        path = Path(self.config_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _provider_models(self, entry: dict[str, Any] | None) -> list[str]:
        """provider 条目模型列表：支持 models:[...] 或旧式 model:'...'。"""
        if not entry:
            return []
        if isinstance(entry.get("models"), list):
            return [str(m) for m in entry["models"] if m]
        if entry.get("model"):
            return [str(entry["model"])]
        return []

    def provider_config(self, provider_name: str | None = None) -> ProviderConfig:
        """解析 provider：注册表优先（含 'primary'），否则回退主 provider（DPIM_LLM_*）。"""
        name = provider_name or self.active_provider
        if name in self.providers:
            return self._entry_provider_config(name, self.providers[name])
        return self._entry_provider_config("primary", None)

    def _entry_provider_config(
        self, name: str, entry: dict[str, Any] | None
    ) -> ProviderConfig:
        """把 provider 条目 + 全局 env 默认合成完整 ProviderConfig。"""
        if entry is None:
            entry = {}
        conf = ProviderConfig(
            name=name,
            base_url=str(entry.get("base_url", "") or self.llm_base_url),
            api_key=str(entry.get("api_key", "") or self.llm_api_key),
            model=self._resolve_model(name, entry),
            timeout=int(entry.get("timeout", self.llm_timeout)),
        )
        # 厂商适配参数：provider 条目优先，未设则用全局 env 默认
        conf.max_tokens = (
            int(entry["max_tokens"]) if entry.get("max_tokens") else self.llm_max_tokens
        )
        conf.enable_thinking = (
            _parse_bool_or_none(str(entry["enable_thinking"]))
            if entry.get("enable_thinking") is not None
            else self.llm_enable_thinking
        )
        conf.thinking_budget = (
            int(entry["thinking_budget"])
            if entry.get("thinking_budget")
            else self.llm_thinking_budget
        )
        conf.thinking_style = str(entry.get("thinking_style", "auto"))
        conf.extra_body = (
            entry.get("extra_body")
            if isinstance(entry.get("extra_body"), dict)
            else None
        )
        conf.structured_mode = (
            str(entry["structured_mode"]) if entry.get("structured_mode") else None
        )
        return conf

    def _resolve_model(self, name: str, entry: dict[str, Any] | None) -> str:
        """模型解析链：active_model（在 provider 模型列表内）→ provider 首个/默认 → env 主模型。"""
        models = self._provider_models(entry)
        if self.active_model and self.active_model in models:
            return self.active_model
        if models:
            return models[0]
        return self.llm_model_name

    def role_model(self, role: str) -> str:
        """角色 → 模型名：角色显式指定则优先，否则用活动 provider 解析的模型。"""
        override = getattr(self, f"agent_{role}_model", "") or ""
        return override if override else self.provider_config().model

    def role_provider(self, role: str) -> ProviderConfig:
        """角色 → ProviderConfig：厂商参数取活动 provider，model 按角色解析。"""
        conf = self.provider_config()
        return ProviderConfig(
            name=conf.name,
            base_url=conf.base_url,
            api_key=conf.api_key,
            model=self.role_model(role),
            timeout=conf.timeout,
            max_tokens=conf.max_tokens,
            enable_thinking=conf.enable_thinking,
            thinking_budget=conf.thinking_budget,
            thinking_style=conf.thinking_style,
            extra_body=conf.extra_body,
            structured_mode=conf.structured_mode,
        )

    def available_models(self) -> list[str]:
        """活动 provider 的可用模型列表（供前端「使用」选择）。"""
        entry = self.providers.get(self.active_provider)
        models = self._provider_models(entry)
        if models:
            return models
        if self.active_provider == "primary":
            return [self.llm_model_name]
        return []


settings = Settings()
