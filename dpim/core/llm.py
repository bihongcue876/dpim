"""共享 LLM 客户端工厂，支持任意 OpenAI 兼容 API"""

from instructor import from_openai
from openai import AsyncOpenAI

from core.config import settings


def create_client() -> AsyncOpenAI:
    key = settings.llm_api_key or "not-set"
    return AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=key,
    )


def create_instructed_client():
    """返回 instructor 包装后的 client，支持 Pydantic 结构化输出"""
    base = create_client()
    return from_openai(base, mode=from_openai.Mode.TOOLS)
