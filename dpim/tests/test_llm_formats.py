"""接口格式适配测试（v1.43）：用**本地真 HTTP 服务器**钉住各协议的线上形状。

为什么不起 fetch/mock 掉 httpx：这一链的全部风险都在「请求到底长什么样」——
路径（`/messages` vs `/responses` vs `/chat/completions`）、鉴权头（`x-api-key` vs
`Authorization: Bearer`）、body 字段名（`system` 是顶层还是消息、`max_tokens` 还是
`max_output_tokens`、`messages` 还是 `input`）。用 MockTransport 断言等于把自己
的假设复述一遍；起一个真服务器收**原始请求**，才验证得了「真的发成这样」。

覆盖：anthropic（形状 / max_tokens 兜底 / 思考字段 / 坏 JSON 回喂重问 / HTTP 错误
分类）、custom（自定路径 + 额外头 + system 进消息）、探测分流（Anthropic 的头、
OpenAI 的 Bearer）、以及网关按格式分派（anthropic 走 httpx、openai 仍走 chat
completions、responses 走 `/v1/responses`）。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from pydantic import BaseModel

from core.config import ProviderConfig, settings
from core.llm import gateway, is_transient_error, probe_models
from core.llm_formats import http_chat_structured


class Payload(BaseModel):
    title: str
    count: int = 0


class _Recorder:
    """记录收到的原始请求；按顺序弹出预置响应（弹完则回 200 空对象）。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[tuple[int, dict]] = []

    def push(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]


@pytest.fixture
def mock_api():
    """本地真 HTTP 服务器（随机端口），返回 `(base_url, recorder)`。"""
    rec = _Recorder()

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"__raw__": raw.decode("utf-8", "replace")}
            rec.requests.append({
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            })
            status, payload = rec.responses.pop(0) if rec.responses else (200, {})
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_POST = _handle  # noqa: N815 —— http.server 要求这两个名字
        do_GET = _handle  # noqa: N815

        def log_message(self, *args) -> None:  # 静音
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", rec
    finally:
        server.shutdown()
        server.server_close()


def _anthropic(base: str, **over) -> ProviderConfig:
    conf = ProviderConfig(
        name="claude", base_url=base, api_key="sk-ant-1", model="claude-sonnet-4-5",
        timeout=10, max_tokens=1024, format="anthropic",
    )
    for key, value in over.items():
        setattr(conf, key, value)
    return conf


def _custom(base: str, **over) -> ProviderConfig:
    conf = ProviderConfig(
        name="gw", base_url=base, api_key="sk-gw", model="local-1",
        timeout=10, format="custom",
    )
    for key, value in over.items():
        setattr(conf, key, value)
    return conf


def _anthropic_text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


# ── anthropic：Messages 协议 ──────────────────────────────────────────────


class TestAnthropicFormat:
    @pytest.mark.asyncio
    async def test_request_shape(self, mock_api):
        base, rec = mock_api
        rec.push(200, _anthropic_text('{"title": "T", "count": 3}'))

        out = await http_chat_structured(_anthropic(base), Payload, "你是裁判", "请判断")

        assert out.title == "T" and out.count == 3
        req = rec.requests[0]
        assert req["path"] == "/v1/messages"
        assert req["headers"]["x-api-key"] == "sk-ant-1"
        assert req["headers"]["anthropic-version"] == "2023-06-01"
        assert "authorization" not in req["headers"]  # Anthropic 不用 Bearer
        assert req["body"]["model"] == "claude-sonnet-4-5"
        assert req["body"]["max_tokens"] == 1024
        assert req["body"]["system"].startswith("你是裁判")
        assert "JSON Schema" in req["body"]["system"]  # 结构化要求随 system 下发
        assert req["body"]["messages"] == [{"role": "user", "content": "请判断"}]
        # 反向断言：不该出现 chat completions / responses 的字段
        assert "input" not in req["body"] and "instructions" not in req["body"]

    @pytest.mark.asyncio
    async def test_max_tokens_is_mandatory_and_defaulted(self, mock_api):
        """`max_tokens` 在 Anthropic 是必填：条目没填也不能发出去一个缺字段的请求。"""
        base, rec = mock_api
        rec.push(200, _anthropic_text('{"title": "T"}'))

        await http_chat_structured(_anthropic(base, max_tokens=None), Payload, "s", "u")

        assert rec.requests[0]["body"]["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_thinking_budget_never_exceeds_max_tokens(self, mock_api):
        """Anthropic 硬性要求 `max_tokens > thinking.budget_tokens`——预算大过兜底时不能原样发出去。

        这是真实缺陷的回归守卫：兜底 4096 + `thinking_budget=8192` 会直接 400；
        即便预算小于上限，思考 token 也**计入** max_tokens，余量不足会被截断成半截 JSON。
        """
        base, rec = mock_api
        rec.push(200, _anthropic_text('{"title": "T"}'))

        await http_chat_structured(
            _anthropic(base, max_tokens=None, thinking_budget=8192), Payload, "s", "u"
        )

        body = rec.requests[0]["body"]
        assert body["thinking"] == {"type": "enabled", "budget_tokens": 8192}
        assert body["max_tokens"] > 8192                    # 严格大于，否则 400
        assert body["max_tokens"] == 8192 + 1024            # 预算 + 余量（留给正文）

    @pytest.mark.asyncio
    async def test_explicit_max_tokens_is_raised_when_too_small(self, mock_api):
        """条目**显式**填了 max_tokens 但比预算小，同样会被 400——抬升并留痕，不静默失败。"""
        base, rec = mock_api
        rec.push(200, _anthropic_text('{"title": "T"}'))

        await http_chat_structured(
            _anthropic(base, max_tokens=2048, thinking_budget=4096), Payload, "s", "u"
        )

        assert rec.requests[0]["body"]["max_tokens"] == 4096 + 1024

    @pytest.mark.asyncio
    async def test_explicit_thinking_off_beats_leftover_budget(self, mock_api):
        """显式「关」必须压过残留的预算值——旧顺序会让「关掉思考」被无声推翻。"""
        base, rec = mock_api
        rec.push(200, _anthropic_text('{"title": "T"}'))

        await http_chat_structured(
            _anthropic(base, max_tokens=2048, thinking_budget=4096, enable_thinking=False),
            Payload, "s", "u",
        )

        body = rec.requests[0]["body"]
        assert body["thinking"] == {"type": "disabled"}   # 关就是关
        assert body["max_tokens"] == 2048                 # 没开思考就不动上限
        assert body["temperature"] == 0.2                 # 关掉后 temperature 照常可用

    @pytest.mark.asyncio
    async def test_thinking_omits_temperature(self, mock_api):
        """开了 extended thinking 就不能带 temperature（Anthropic 要求 1）。"""
        base, rec = mock_api
        rec.push(200, _anthropic_text('{"title": "T"}'))
        await http_chat_structured(_anthropic(base, thinking_budget=2048), Payload, "s", "u")
        body = rec.requests[0]["body"]
        assert body["thinking"] == {"type": "enabled", "budget_tokens": 2048}
        assert "temperature" not in body

        rec.push(200, _anthropic_text('{"title": "T"}'))
        await http_chat_structured(
            _anthropic(base, enable_thinking=False), Payload, "s", "u"
        )
        body = rec.requests[1]["body"]
        assert body["thinking"] == {"type": "disabled"}
        assert body["temperature"] == 0.2

    @pytest.mark.asyncio
    async def test_bad_json_is_reasked_with_error(self, mock_api):
        """结构化校验失败 → 把坏输出与校验错误回喂重问（不是静默返回坏数据）。"""
        base, rec = mock_api
        rec.push(200, _anthropic_text("抱歉，我不能这样做。"))
        rec.push(200, _anthropic_text('```json\n{"title": "好"}\n```'))

        out = await http_chat_structured(_anthropic(base), Payload, "s", "u", max_retries=2)

        assert out.title == "好"
        assert len(rec.requests) == 2
        second = rec.requests[1]["body"]["messages"]
        assert [m["role"] for m in second] == ["user", "assistant", "user"]
        assert second[1]["content"].startswith("抱歉")
        assert "不是合法 JSON" in second[2]["content"]

    @pytest.mark.asyncio
    async def test_gives_up_with_clear_error(self, mock_api):
        base, rec = mock_api
        for _ in range(3):
            rec.push(200, _anthropic_text("还是不对"))

        with pytest.raises(ValueError) as excinfo:
            await http_chat_structured(_anthropic(base), Payload, "s", "u", max_retries=2)

        assert "结构化输出解析失败" in str(excinfo.value)
        assert len(rec.requests) == 3  # 首次 + 2 次重问

    @pytest.mark.asyncio
    async def test_http_error_visible_and_classified(self, mock_api):
        """错误原文要带状态码与响应体（界面直接可读）；5xx/429 才算可重试。"""
        base, rec = mock_api
        rec.push(401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            await http_chat_structured(_anthropic(base), Payload, "s", "u", max_retries=0)
        assert excinfo.value.response.status_code == 401
        assert is_transient_error(excinfo.value) is False  # 4xx 不可自愈

        rec.push(503, {"error": "overloaded"})
        with pytest.raises(httpx.HTTPStatusError) as excinfo2:
            await http_chat_structured(_anthropic(base), Payload, "s", "u", max_retries=0)
        assert is_transient_error(excinfo2.value) is True  # 5xx 可重试

    @pytest.mark.asyncio
    async def test_missing_text_block_reports_reason(self, mock_api):
        """只回了 thinking 块（没文本）时如实报错，别把空串当成功。"""
        base, rec = mock_api
        rec.push(200, {
            "content": [{"type": "thinking", "thinking": "..."}],
            "stop_reason": "max_tokens",
        })

        with pytest.raises(ValueError) as excinfo:
            await http_chat_structured(_anthropic(base), Payload, "s", "u", max_retries=0)
        assert "没有文本块" in str(excinfo.value)


# ── custom：自定路径 + 额外请求头（仍按 chat completions 收发）─────────────


class TestCustomFormat:
    @pytest.mark.asyncio
    async def test_path_headers_and_body(self, mock_api):
        base, rec = mock_api
        rec.push(200, {"choices": [{"message": {"content": '{"title": "C"}'}}]})
        conf = _custom(
            base, api_path="chat/custom",   # 故意不写前导斜杠：应自动补
            extra_headers={"X-Tenant": "dpim"},
        )

        out = await http_chat_structured(conf, Payload, "系统提示", "用户输入")

        assert out.title == "C"
        req = rec.requests[0]
        assert req["path"] == "/v1/chat/custom"
        assert req["headers"]["authorization"] == "Bearer sk-gw"
        assert req["headers"]["x-tenant"] == "dpim"
        # system 必须是消息列表的第一条（不像 Anthropic 是顶层字段）
        first = req["body"]["messages"][0]
        assert first["role"] == "system"
        assert first["content"].startswith("系统提示")
        assert req["body"]["messages"][1] == {"role": "user", "content": "用户输入"}

    @pytest.mark.asyncio
    async def test_default_path_and_extra_body(self, mock_api):
        base, rec = mock_api
        rec.push(200, {"choices": [{"message": {"content": '{"title": "D"}'}}]})
        conf = _custom(base, max_tokens=512, extra_body={"top_k": 20})

        await http_chat_structured(conf, Payload, "s", "u")

        req = rec.requests[0]
        assert req["path"] == "/v1/chat/completions"  # 未填 api_path → 默认路径
        assert req["body"]["max_tokens"] == 512
        assert req["body"]["top_k"] == 20  # 厂商参数透传


# ── 探测分流 ─────────────────────────────────────────────────────────────


class TestProbeByFormat:
    @pytest.mark.asyncio
    async def test_anthropic_probe_uses_api_key_header(self, mock_api):
        base, rec = mock_api
        rec.push(200, {"data": [{"id": "claude-a"}, {"id": "claude-b"}, {"display_name": "无 id"}]})

        models = await probe_models(_anthropic(base))

        assert models == ["claude-a", "claude-b"]
        req = rec.requests[0]
        assert req["path"] == "/v1/models"
        assert req["headers"]["x-api-key"] == "sk-ant-1"
        assert req["headers"]["anthropic-version"] == "2023-06-01"

    @pytest.mark.asyncio
    async def test_openai_probe_uses_bearer(self, mock_api):
        base, rec = mock_api
        rec.push(200, {"object": "list", "data": [{"id": "m1"}, {"id": "m2"}, {"id": ""}]})
        conf = ProviderConfig(
            name="sf", base_url=base, api_key="sk-sf", model="m1", timeout=10,
        )

        models = await probe_models(conf)

        assert models == ["m1", "m2"]  # 空 id 剔除
        req = rec.requests[0]
        assert req["path"] == "/v1/models"
        assert req["headers"]["authorization"] == "Bearer sk-sf"


# ── 网关按格式分派 ────────────────────────────────────────────────────────


class TestGatewayDispatch:
    @pytest.mark.asyncio
    async def test_anthropic_provider_goes_over_http(self, mock_api, monkeypatch):
        base, rec = mock_api
        rec.push(200, _anthropic_text('{"title": "G"}'))
        monkeypatch.setattr(settings, "providers", {
            "claude": {"base_url": base, "api_key": "k", "models": ["claude-x"],
                       "format": "anthropic"},
        })
        monkeypatch.setattr(settings, "active_provider", "claude")

        out = await gateway.chat_structured("cr", Payload, "s", "u")

        assert out.title == "G"
        assert rec.paths() == ["/v1/messages"]

    @pytest.mark.asyncio
    async def test_openai_provider_still_uses_chat_completions(self, mock_api, monkeypatch):
        """老路径零变化：默认格式仍走 chat completions（不因为新格式而改道）。"""
        base, rec = mock_api
        rec.push(200, {
            "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "local-1",
            "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"title": "O"}'},
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
        monkeypatch.setattr(settings, "providers", {
            "local": {"base_url": base, "api_key": "k", "models": ["local-1"]},
        })
        monkeypatch.setattr(settings, "active_provider", "local")

        out = await gateway.chat_structured("cr", Payload, "s", "u")

        assert out.title == "O"
        assert rec.paths() == ["/v1/chat/completions"]

    @pytest.mark.asyncio
    async def test_responses_provider_uses_responses_endpoint(self, mock_api, monkeypatch):
        """responses 格式走 `/v1/responses`：body 是 `input`，工具调用在 `output` 里。"""
        base, rec = mock_api
        rec.push(200, {
            "id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-x",
            "status": "completed", "parallel_tool_calls": True, "tool_choice": "required",
            "tools": [],
            "output": [{
                "type": "function_call", "id": "fc_1", "call_id": "call_1",
                "name": "Payload", "arguments": '{"title": "R"}', "status": "completed",
            }],
        })
        monkeypatch.setattr(settings, "providers", {
            "oa": {"base_url": base, "api_key": "k", "models": ["gpt-x"],
                   "format": "responses", "max_tokens": 777},
        })
        monkeypatch.setattr(settings, "active_provider", "oa")

        out = await gateway.chat_structured("cr", Payload, "s", "u")

        assert out.title == "R"
        req = rec.requests[0]
        assert req["path"] == "/v1/responses"
        assert "messages" not in req["body"]      # Responses 不接受 messages
        assert "max_tokens" not in req["body"]    # 参数名换成 max_output_tokens（否则 SDK 拒收）
        assert req["body"]["max_output_tokens"] == 777
        # instructor 把整段 messages 作为 input 传：Responses 允许 system/developer 角色条目
        assert [m["role"] for m in req["body"]["input"]] == ["system", "user"]
        # 结构化输出走工具调用（RESPONSES_TOOLS）：强制调用该 response_model
        assert req["body"]["tool_choice"] == {"type": "function", "name": "Payload"}
