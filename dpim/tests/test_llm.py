"""LLM 网关厂商适配层测试（SiliconFlow / DeepSeek / llama.cpp 透传）"""

import httpx
from openai import APIStatusError

from core.config import ProviderConfig
from core.llm import _client_for, _is_local_host, _request_extra, is_transient_error


def make_conf(**kw):
    defaults = dict(
        name="t",
        base_url="http://localhost:5091/v1",
        api_key="1",
        model="m",
        timeout=120,
    )
    defaults.update(kw)
    return ProviderConfig(**defaults)


def test_is_local_host():
    assert _is_local_host("http://localhost:5091/v1")
    assert _is_local_host("http://127.0.0.1:11434/v1")
    assert not _is_local_host("https://api.siliconflow.cn/v1")
    assert not _is_local_host("https://api.deepseek.com/v1")


def test_request_extra_siliconflow_top_level():
    conf = make_conf(
        base_url="https://api.siliconflow.cn/v1",
        enable_thinking=True,
        thinking_budget=2048,
    )
    assert _request_extra(conf) == {"enable_thinking": True, "thinking_budget": 2048}


def test_request_extra_local_auto_uses_chat_template():
    conf = make_conf(base_url="http://localhost:5091/v1", enable_thinking=False)
    assert _request_extra(conf) == {"chat_template_kwargs": {"enable_thinking": False}}


def test_request_extra_explicit_style():
    conf = make_conf(
        base_url="https://api.siliconflow.cn/v1",
        enable_thinking=False,
        thinking_style="chat_template_kwargs",
    )
    assert _request_extra(conf) == {"chat_template_kwargs": {"enable_thinking": False}}


def test_request_extra_passthrough_priority():
    """extra_body 透传优先级最高：显式 enable_thinking 可被透传覆盖。"""
    conf = make_conf(
        base_url="https://api.siliconflow.cn/v1",
        enable_thinking=True,
        extra_body={"reasoning_effort": "high", "enable_thinking": False},
    )
    body = _request_extra(conf)
    assert body["enable_thinking"] is False
    assert body["reasoning_effort"] == "high"


def test_request_extra_none_by_default():
    assert _request_extra(make_conf()) == {}
    assert _request_extra(make_conf(enable_thinking=None, thinking_budget=0)) == {}


def test_client_for_applies_timeout():
    conf = make_conf(timeout=321)
    client = _client_for(conf)
    assert client.timeout == 321


def _status_error(code: int) -> APIStatusError:
    req = httpx.Request("POST", "http://x/v1/chat/completions")
    resp = httpx.Response(code, request=req)
    return APIStatusError(f"http {code}", response=resp, body=None)


def test_transient_4xx_not_transient():
    """4xx 客户端错误（如 402 余额不足）不可自愈 → 判 failed，不无限重试。"""
    assert not is_transient_error(_status_error(402))
    assert not is_transient_error(_status_error(401))
    assert not is_transient_error(_status_error(400))


def test_transient_5xx_and_429_transient():
    assert is_transient_error(_status_error(500))
    assert is_transient_error(_status_error(503))
    assert is_transient_error(_status_error(429))
    assert is_transient_error(_status_error(408))
