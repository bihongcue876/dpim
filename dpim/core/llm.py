"""共享 LLM 客户端工厂 — BYOK 多模型网关，按 Agent 角色路由。

支持多个 OpenAI 兼容提供商（DeepSeek / Ollama / llama.cpp / OpenRouter 等），
按角色（cr/in/gr/meta）解析 base_url、api_key 与 model，并缓存客户端。

chat_structured 封装「一次有效调用」：调用方把该阶段所需的全部上下文
一次性打包进单次 messages，由 LLM 返回 Pydantic 结构化结果。

结构化输出模式（DPIM_LLM_STRUCTURED_MODE）：
- md_json（默认）：instructor 解析 content 中的 JSON，兼容 llama.cpp/Qwen3.5
  （这些服务不返回 tool_calls，而是把 JSON 直接放在 content 里）。
- json：instructor 使用 response_format=json_object（需服务支持）。
- tools：instructor 使用函数调用（tool_calls），适合原生工具调用服务。
"""

from collections import deque
from dataclasses import dataclass
from time import time
from typing import Any, TypeVar, cast

import instructor
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from pydantic import BaseModel

from core.config import ProviderConfig, settings

M = TypeVar("M", bound=BaseModel)

_STRUCTURED_MODES: dict[str, instructor.Mode] = {
    "md_json": instructor.Mode.MD_JSON,
    "json": instructor.Mode.JSON,
    "tools": instructor.Mode.TOOLS,
}


def _client_for(conf: ProviderConfig) -> AsyncOpenAI:
    key = conf.api_key or "not-set"
    # timeout 应用 provider 配置（默认 DPIM_LLM_TIMEOUT，本地模型放宽）
    return AsyncOpenAI(base_url=conf.base_url, api_key=key, timeout=conf.timeout)


def is_transient_error(e: Exception) -> bool:
    """瞬时错误判定：超时 / 断连 / 5xx 服务端错误。

    这类错误重试可能成功（本地模型慢、加载中、单槽忙碌），
    不应将事件判死为 failed，而应回到 indexed 等待补偿重试。
    """
    if isinstance(e, (APITimeoutError, APIConnectionError, APIStatusError)):
        return True
    import httpx
    # httpx 底层传输错误：ReadTimeout / ConnectError / ReadError 等
    if isinstance(e, httpx.TransportError):
        return True
    return False


# ── AI 调用日志（环形缓冲，供前端观测 LLM 发了什么）──

@dataclass
class LLMCallLog:
    role: str
    timestamp: float
    model: str
    input_preview: str
    output: str
    error: str = ""


_llm_logs: deque[LLMCallLog] = deque(maxlen=50)


def log_llm_call(role: str, model: str, user: str, output: str, error: str = "") -> None:
    _llm_logs.appendleft(LLMCallLog(
        role=role,
        timestamp=time(),
        model=model,
        input_preview=user[:2000],
        output=output[:2000],
        error=error[:2000],
    ))


def get_llm_logs(limit: int = 30) -> list[dict[str, Any]]:
    """返回最近 LLM 调用日志（新→旧）。"""
    return [log.__dict__ for log in list(_llm_logs)[:limit]]


def clear_llm_logs() -> None:
    """清空调用日志（测试用）。"""
    _llm_logs.clear()


class LLMGateway:
    """BYOK 多模型网关：按角色返回客户端/模型名，并缓存实例。"""

    def __init__(self) -> None:
        self._client_cache: dict[tuple[str, str], AsyncOpenAI] = {}
        self._instructed_cache: dict[tuple[str, str], Any] = {}

    def client(self, role: str = "cr") -> AsyncOpenAI:
        """按角色返回基础 AsyncOpenAI 客户端。"""
        conf = settings.role_provider(role)
        key = (conf.base_url, conf.api_key)
        if key not in self._client_cache:
            self._client_cache[key] = _client_for(conf)
        return self._client_cache[key]

    def instructed(self, role: str = "cr") -> Any:
        """按角色返回 instructor 包装客户端（支持 response_model 结构化输出）。"""
        conf = settings.role_provider(role)
        key = (conf.base_url, conf.api_key)
        if key not in self._instructed_cache:
            mode = _STRUCTURED_MODES.get(settings.llm_structured_mode, instructor.Mode.MD_JSON)
            self._instructed_cache[key] = instructor.from_openai(
                self.client(role), mode=mode
            )
        return self._instructed_cache[key]

    async def chat_structured(
        self,
        role: str,
        response_model: type[M],
        system: str,
        user: str,
        temperature: float = 0.2,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> M:
        """一次有效调用：system + user 打包进单次 messages，返回结构化结果。

        max_retries：instructor 在结构化校验失败时自动重问的次数（降低 JSON 解析失败率）。
        """
        client = self.instructed(role)
        model = settings.role_model(role)
        try:
            result = await client.chat.completions.create(
                model=model,
                response_model=response_model,
                temperature=temperature,
                max_retries=max_retries,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                **kwargs,
            )
            log_llm_call(role, model, user, str(result))
            return cast(M, result)
        except Exception as e:
            log_llm_call(role, model, user, "", f"{type(e).__name__}: {e}")
            raise


gateway = LLMGateway()


def create_client() -> AsyncOpenAI:
    """兼容旧接口：默认主 provider 客户端（compensator 使用）。"""
    return gateway.client("cr")


def create_instructed_client() -> Any:
    """兼容旧接口：默认主 provider 的 instructor 包装客户端。"""
    return gateway.instructed("cr")
