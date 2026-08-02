"""共享 LLM 客户端工厂 — BYOK 多模型网关，按 Agent 角色路由。

支持多个 OpenAI 兼容提供商（DeepSeek / Ollama / OpenRouter 等），
按角色（cr/in/gr/meta）解析 base_url、api_key 与 model，并缓存客户端。

chat_structured 封装「一次有效调用」：调用方把该阶段所需的全部上下文
一次性打包进单次 messages，由 LLM 返回 Pydantic 结构化结果。
"""

from typing import Any, TypeVar, cast

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel

from core.config import ProviderConfig, settings

M = TypeVar("M", bound=BaseModel)


def _client_for(conf: ProviderConfig) -> AsyncOpenAI:
    key = conf.api_key or "not-set"
    return AsyncOpenAI(base_url=conf.base_url, api_key=key)


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
            self._instructed_cache[key] = instructor.from_openai(
                self.client(role), mode=instructor.Mode.TOOLS
            )
        return self._instructed_cache[key]

    async def chat_structured(
        self,
        role: str,
        response_model: type[M],
        system: str,
        user: str,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> M:
        """一次有效调用：system + user 打包进单次 messages，返回结构化结果。"""
        client = self.instructed(role)
        model = settings.role_model(role)
        result = await client.chat.completions.create(
            model=model,
            response_model=response_model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        return cast(M, result)


gateway = LLMGateway()


def create_client() -> AsyncOpenAI:
    """兼容旧接口：默认主 provider 客户端（compensator 使用）。"""
    return gateway.client("cr")


def create_instructed_client() -> Any:
    """兼容旧接口：默认主 provider 的 instructor 包装客户端。"""
    return gateway.instructed("cr")
