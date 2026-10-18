"""非「OpenAI 兼容 Chat Completions」协议的 LLM 调用适配（v1.43）。

**为什么需要**：`core/llm.py` 的网关建在 `AsyncOpenAI` + `instructor` 之上，
唯一调用是 `chat.completions.create`——只认 OpenAI 兼容 Chat Completions。
于是另外两套主流协议**完全接不上**（连模型列表都拉不出来）：

- **anthropic**：`POST {base}/messages`，`x-api-key` + `anthropic-version` 头，
  `system` 是**顶层字段**、`max_tokens` **必填**、响应取 `content[].text`；
- **custom**：自定路径 + 额外请求头，仍按 chat completions 形状收发（自建网关）。

（第三套 **responses** 不在这里——OpenAI 的 `/v1/responses` 由 `openai` SDK 自带的
`.responses` + instructor 的 `Mode.RESPONSES_TOOLS` 官方路径支持，见 `core/llm.py`。）

**为什么不用 instructor 的 anthropic provider**：它需要 `anthropic` SDK，而本项目
依赖表里没有；本环境也无法安全新增（`uv lock` 需联网重建，沙箱里 `uv` 跑不起来）。
改用已装的 `httpx` 实现——**零新依赖**，且自建「Anthropic 兼容」网关（换 base_url）
同样能用。

**结构化输出**：Anthropic Messages 没有原生 JSON Schema 输出，故本模块按
「system 里附 JSON Schema → 只许输出一个 JSON 对象 → 解析 → Pydantic 校验 →
把校验错误回喂重问（至多 max_retries 次）」实现，与 instructor 的 md_json 同语义：
**一次有效调用**，校验失败自动重问，不是静默返回坏数据。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from core.config import (
    ANTHROPIC_DEFAULT_MAX_TOKENS,
    ANTHROPIC_THINKING_HEADROOM,
    ANTHROPIC_VERSION,
    DEFAULT_API_PATHS,
    ProviderConfig,
)
from core.security import sanitize_secret

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
# 重问时把模型的坏输出截断回喂（长输出的错误信息没价值，白烧 token）
_MAX_ECHO_CHARS = 2000


def api_url(conf: ProviderConfig) -> str:
    """请求地址：`base_url` + 路径（`api_path` 仅 custom 有意义；缺省按格式默认）。

    容忍两种常见填法：`api_path` 没写前导 `/`，或 `base_url` 结尾带 `/`。
    """
    path = (conf.api_path or "").strip() or DEFAULT_API_PATHS.get(conf.format, "/chat/completions")
    if not path.startswith("/"):
        path = "/" + path
    return conf.base_url.rstrip("/") + path


def request_headers(conf: ProviderConfig) -> dict[str, str]:
    """按格式组装鉴权头；`extra_headers` 最后合并（优先级最高，可覆盖默认头）。

    值一律过 `sanitize_secret()`：HTTP 头里带控制字符（跨行粘贴的密钥很常见）会让客户端
    **直接报错，而报错正文回显整条头值**（含真钥）——那段原文会进界面与日志（实测见该函数注释）。
    """
    headers: dict[str, str] = {"content-type": "application/json"}
    api_key = sanitize_secret(conf.api_key)
    if conf.format == "anthropic":
        # Anthropic 用 x-api-key（不是 Bearer），且必须带 anthropic-version
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = ANTHROPIC_VERSION
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if conf.extra_headers:
        headers.update(
            {str(k): sanitize_secret(str(v)) for k, v in conf.extra_headers.items()}
        )
    return headers


def _schema_hint(response_model: type[BaseModel]) -> str:
    """附在 system 末尾的「输出格式」段：只要一个 JSON 对象 + 其 JSON Schema。"""
    schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
    return (
        "\n\n【输出格式】只输出**一个 JSON 对象**，不要解释、不要前后缀、不要 Markdown "
        "代码块标记。它必须符合以下 JSON Schema：\n" + schema
    )


def extract_json(text: str) -> str:
    """从模型输出里取出第一个 JSON 对象/数组的文本。

    容忍三类常见噪声：```json 围栏、JSON 前后的客套话、字符串里的括号。
    取不到时抛 `ValueError`（调用方据此重问，而不是把坏数据当结果）。
    """
    raw = (text or "").strip()
    fenced = _FENCE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    starts = [i for i in (raw.find("{"), raw.find("[")) if i >= 0]
    if not starts:
        raise ValueError("输出里找不到 JSON 对象")
    start = min(starts)
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return raw[start:i + 1]
    return raw[start:]


def _thinking_spec(conf: ProviderConfig, max_tokens: int) -> dict[str, Any]:
    """Anthropic 的思考开关：映射到 `thinking`（extended thinking）。

    优先级：**显式关**（`enable_thinking=False`）> 显式预算（`thinking_budget`）> 显式开。
    显式关必须压过预算——旧顺序（预算优先）会让一个**残留的预算值无声推翻「关掉思考」**：
    用户以为关了，实际开着（还连带丢掉 temperature、白烧 token）。三态都不设 → 不干预。

    注意：开了 thinking 就**不能带 temperature**（Anthropic 要求 temperature=1），
    故由调用方在此时省略 temperature。
    """
    if conf.enable_thinking is False:
        return {"thinking": {"type": "disabled"}}
    if conf.thinking_budget:
        return {"thinking": {"type": "enabled", "budget_tokens": int(conf.thinking_budget)}}
    if conf.enable_thinking is True:
        budget = min(4096, max(1, max_tokens // 2))
        return {"thinking": {"type": "enabled", "budget_tokens": budget}}
    return {}


def _anthropic_limits(conf: ProviderConfig) -> tuple[int, dict[str, Any]]:
    """定 `max_tokens` 与 `thinking`，保证 **max_tokens > budget_tokens**（Anthropic 硬性要求）。

    两步走的原因：预算与上限互相牵制——① Anthropic 要求 `max_tokens` **大于** `budget_tokens`，
    不满足直接 400；② 思考 token **计入** `max_tokens`，余量不够就会在思考结束前被
    `stop_reason=max_tokens` 截断（半截 JSON → 校验必失败、白烧一次调用）。
    故：先按「条目值 → 全局 `DPIM_LLM_MAX_TOKENS` → 兜底 4096」定上限 → 算出 thinking →
    发现余量不足就**抬到「预算 + 余量」**并 WARNING 留痕（日志页可见，不静默）。
    """
    requested = int(conf.max_tokens or 0) or ANTHROPIC_DEFAULT_MAX_TOKENS
    thinking = _thinking_spec(conf, requested)
    budget = int(thinking.get("thinking", {}).get("budget_tokens") or 0)
    if budget and requested <= budget:
        raised = budget + ANTHROPIC_THINKING_HEADROOM
        logger.warning(
            "anthropic：max_tokens=%s 未大于思考预算 %s（会被 400 或截断），本次按 %s 发送",
            requested, budget, raised,
        )
        requested = raised
    return requested, thinking


def build_body(
    conf: ProviderConfig,
    system: str,
    turns: list[dict[str, str]],
    temperature: float,
) -> dict[str, Any]:
    """按格式组装请求体（`turns` = 逐轮 user/assistant 消息，含重问轮）。"""
    if conf.format == "anthropic":
        max_tokens, thinking = _anthropic_limits(conf)
        body: dict[str, Any] = {
            "model": conf.model,
            # max_tokens 在 Anthropic 是**必填**：条目没填就兜底（否则 400）
            "max_tokens": max_tokens,
            "system": system,
            "messages": turns,
        }
        if thinking:
            body.update(thinking)
        # temperature 只在**开启**思考时省略：Anthropic 要求「开了 thinking 就 temperature=1」，
        # 而 thinking=disabled 时 temperature 照常可用（别顺手把可调项也砍掉）
        if thinking.get("thinking", {}).get("type") != "enabled":
            body["temperature"] = temperature
        return body
    # custom：仍按 OpenAI chat completions 形状（自定路径/请求头）——
    # system 必须作为**第一条消息**（不像 Anthropic 那样是顶层字段）
    body: dict[str, Any] = {
        "model": conf.model,
        "messages": [{"role": "system", "content": system}, *turns],
        "temperature": temperature,
    }
    if conf.max_tokens:
        body["max_tokens"] = int(conf.max_tokens)
    if conf.extra_body:
        body.update(conf.extra_body)  # 厂商参数透传（与 openai 路径同语义）
    return body


def extract_text(conf: ProviderConfig, data: dict[str, Any]) -> str:
    """按格式从响应里取正文文本（取不到时抛错，绝不返回空串当成功）。"""
    if conf.format == "anthropic":
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise ValueError(f"响应里没有 content 数组：{str(data)[:300]}")
        texts = [
            str(b.get("text") or "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        text = "\n".join(t for t in texts if t)
        if not text:
            # 只返回了 thinking 块或空内容：如实报出来（含 stop_reason，便于判断是否被截断）
            raise ValueError(
                f"响应里没有文本块（stop_reason={data.get('stop_reason')}）：{str(data)[:300]}"
            )
        return text
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError(f"响应里没有 choices 数组：{str(data)[:300]}")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # 部分网关返回分段数组
        return "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    if content is None:
        raise ValueError(f"响应里没有 message.content：{str(data)[:300]}")
    return str(content)


async def http_chat_structured(
    conf: ProviderConfig,
    response_model: type[M],
    system: str,
    user: str,
    temperature: float = 0.2,
    max_retries: int = 2,
) -> M:
    """一次有效调用（httpx 版）：anthropic / custom 共用。

    失败语义与 instructor 路径对齐：结构化校验失败 → 把错误回喂重问（至多
    `max_retries` 次）；网络/HTTP 错误原样抛出（由 `is_transient_error` 判定
    可否重试），错误信息里带上状态码与响应片段，便于界面直接展示原因。
    """
    from core.llm import log_llm_call  # 局部导入：避免与 core.llm 循环依赖

    url = api_url(conf)
    headers = request_headers(conf)
    system_with_hint = system + _schema_hint(response_model)
    turns: list[dict[str, str]] = [{"role": "user", "content": user}]
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=conf.timeout) as client:
        for attempt in range(max_retries + 1):
            body = build_body(conf, system_with_hint, turns, temperature)
            try:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _error_detail(exc)
                log_llm_call(conf.name, conf.model, user, "", detail)
                raise
            except httpx.HTTPError as exc:
                detail = f"{type(exc).__name__}: {exc}"
                log_llm_call(conf.name, conf.model, user, "", detail)
                raise
            data = resp.json()
            try:
                text = extract_text(conf, data)
                result = response_model.model_validate_json(extract_json(text))
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    preview = str(data)[:1000]
                    log_llm_call(
                        conf.name, conf.model, user, preview, f"结构化解析失败: {exc}"
                    )
                    raise ValueError(
                        f"{conf.format} 结构化输出解析失败（已重问 {attempt} 次）：{exc}"
                    ) from exc
                logger.info(
                    "%s 结构化输出不合格（第 %d 次），回喂错误重问：%s",
                    conf.format, attempt + 1, exc,
                )
                # 把模型的坏输出 + 校验错误一起回喂（instructor 的 reask 同思路）
                turns = [
                    *turns,
                    {"role": "assistant", "content": text[:_MAX_ECHO_CHARS]},
                    {
                        "role": "user",
                        "content": (
                            "上面的输出不是合法 JSON 或不符合给定 Schema："
                            f"{exc}\n请只输出一个符合 Schema 的 JSON 对象，不要任何其它内容。"
                        ),
                    },
                ]
                continue
            log_llm_call(conf.name, conf.model, user, str(result))
            return result
    raise ValueError(f"{conf.format} 调用失败：{last_error}")


def _error_detail(exc: httpx.HTTPStatusError) -> str:
    """HTTP 错误摘要：状态码 + 响应片段（截 400 字符，界面直接可读）。"""
    body = ""
    try:
        body = exc.response.text[:400]
    except Exception:  # 响应体读不出来也不能再抛一个异常盖住原始错误
        body = ""
    if not body:
        return f"HTTP {exc.response.status_code}"
    return f"HTTP {exc.response.status_code}: {body}"


async def probe_models_anthropic(conf: ProviderConfig) -> list[str]:
    """Anthropic 的模型列表：`GET {base}/models`（同一套头，响应仍是 `{data:[{id}]}`）。

    失败时把**状态码 + 响应片段**一起抛出（如 401 的 `invalid x-api-key`）——
    只报「401 Unauthorized」等于没说原因，界面也就无从自查。
    """
    url = conf.base_url.rstrip("/") + "/models"
    async with httpx.AsyncClient(timeout=conf.timeout) as client:
        try:
            resp = await client.get(url, headers=request_headers(conf))
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(_error_detail(exc)) from exc
        data = resp.json()
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"响应里没有 data 数组：{str(data)[:300]}")
    return [
        str(r.get("id"))
        for r in rows
        if isinstance(r, dict) and r.get("id")
    ]
