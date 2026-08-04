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
    """瞬时错误判定：超时 / 断连 / 5xx 服务端错误（可重试）。

    遍历异常链（__cause__/__context__）：instructor 等重试包装异常（如
    InstructorRetryException）重试用尽后抛出，其底层 cause 可能仍是瞬时错误，
    不能因包装层而把事件判死。4xx 客户端错误（401/402/403/400 等）不可自愈
    → 链上遇到即判定非瞬时。
    """
    seen: set[int] = set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, (APITimeoutError, APIConnectionError)):
            return True
        if isinstance(e, APIStatusError):
            if 500 <= e.status_code <= 599 or e.status_code in (408, 429):
                return True
            return False  # 4xx 客户端错误：不可自愈，终止链遍历
        import httpx
        # httpx 底层传输错误：ReadTimeout / ConnectError / ReadError 等
        if isinstance(e, httpx.TransportError):
            return True
        e = e.__cause__ or e.__context__
    return False


# ── 厂商适配：按 provider 组装 OpenAI 请求的额外参数 ──

def _is_local_host(base_url: str) -> bool:
    """本地地址判定：llama.cpp / Ollama 等本机服务。"""
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")


def _request_extra(conf: ProviderConfig) -> dict[str, Any]:
    """把 provider 的厂商适配参数合成为请求 extra_body。

    - enable_thinking：SiliconFlow/DeepSeek 用顶层字段；llama.cpp 用 chat_template_kwargs；
      auto 模式下本地地址自动选 chat_template_kwargs。
    - thinking_budget：顶层字段（SiliconFlow 等支持）。
    - extra_body：provider 声明的任意厂商参数透传（如 reasoning_effort），最后合并、优先级最高。
    """
    body: dict[str, Any] = {}
    if conf.enable_thinking is not None:
        use_template = conf.thinking_style == "chat_template_kwargs" or (
            conf.thinking_style == "auto" and _is_local_host(conf.base_url)
        )
        if use_template:
            body["chat_template_kwargs"] = {"enable_thinking": conf.enable_thinking}
        else:
            body["enable_thinking"] = conf.enable_thinking
    if conf.thinking_budget:
        body["thinking_budget"] = conf.thinking_budget
    if conf.extra_body:
        body.update(conf.extra_body)
    return body


# ── AI 调用日志（环形缓冲，供前端观测 LLM 发了什么）──

@dataclass
class LLMCallLog:
    role: str
    timestamp: float
    model: str
    input: str
    output: str
    error: str = ""


_llm_logs: deque[LLMCallLog] = deque(maxlen=50)
_LOG_PREVIEW_LEN = 2000


def log_llm_call(role: str, model: str, user: str, output: str, error: str = "") -> None:
    # 完整内容入缓冲；是否截断由读取侧（get_llm_logs）按需决定
    _llm_logs.appendleft(LLMCallLog(
        role=role,
        timestamp=time(),
        model=model,
        input=user,
        output=output,
        error=error,
    ))


def get_llm_logs(limit: int = 30, full: bool = False) -> list[dict[str, Any]]:
    """返回最近 LLM 调用日志（新→旧）。

    full=False（默认）：截断为 input_preview/output/error（各 ≤2000 字符），
    兼容旧客户端与协议；full=True：返回完整 input/output/error。
    """
    logs = list(_llm_logs)[:limit]
    if full:
        return [log.__dict__ for log in logs]
    return [
        {
            "role": log.role,
            "timestamp": log.timestamp,
            "model": log.model,
            "input_preview": log.input[:_LOG_PREVIEW_LEN],
            "output": log.output[:_LOG_PREVIEW_LEN],
            "error": log.error[:_LOG_PREVIEW_LEN],
        }
        for log in logs
    ]


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
        """按角色返回 instructor 包装客户端（支持 response_model 结构化输出）。

        缓存键含结构化模式：不同 provider 可声明不同 structured_mode。
        """
        conf = settings.role_provider(role)
        mode = _STRUCTURED_MODES.get(
            conf.structured_mode or settings.llm_structured_mode, instructor.Mode.MD_JSON
        )
        key = (conf.base_url, conf.api_key, mode)
        if key not in self._instructed_cache:
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
        厂商适配：按 provider 组装 max_tokens 与 extra_body（思考开关/预算/任意透传）。
        """
        conf = settings.role_provider(role)
        client = self.instructed(role)
        model = conf.model
        request_kwargs = dict(kwargs)
        if conf.max_tokens:
            request_kwargs.setdefault("max_tokens", conf.max_tokens)
        extra = _request_extra(conf)
        if extra:
            merged = dict(request_kwargs.get("extra_body") or {})
            merged.update(extra)
            request_kwargs["extra_body"] = merged
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
                **request_kwargs,
            )
            log_llm_call(role, model, user, str(result))
            return cast(M, result)
        except Exception as e:
            log_llm_call(role, model, user, "", f"{type(e).__name__}: {e}")
            raise


    async def embed(self, texts: list[str], role: str = "cr") -> list[list[float]]:
        """文本向量化（OpenAI 兼容 /v1/embeddings，Ollama/SiliconFlow 等可用）。

        嵌入服务独立配置：embedding_base_url/api_key（全局 env 或 provider 条目），
        未配置时跟随活动 provider 的 base_url/api_key；模型取 provider 条目/全局
        embedding_model。未配置模型或请求失败时抛异常，由调用方静默降级回退。
        返回向量列表，顺序与输入 texts 一致。
        """
        conf = settings.role_provider(role)
        model = conf.embedding_model or settings.embedding_model
        if not model:
            raise RuntimeError("embedding_model 未配置，语义检索不可用")
        embed_client = AsyncOpenAI(
            base_url=conf.embedding_base_url or conf.base_url,
            api_key=conf.embedding_api_key or conf.api_key,
            timeout=conf.timeout,
        )
        resp = await embed_client.embeddings.create(model=model, input=texts)
        ordered = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in ordered]


gateway = LLMGateway()


def create_client() -> AsyncOpenAI:
    """兼容旧接口：默认主 provider 客户端（compensator 使用）。"""
    return gateway.client("cr")


def create_instructed_client() -> Any:
    """兼容旧接口：默认主 provider 的 instructor 包装客户端。"""
    return gateway.instructed("cr")
