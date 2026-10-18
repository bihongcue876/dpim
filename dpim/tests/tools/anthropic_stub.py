r"""Anthropic 协议桩模型服务 —— **故障注入 / 端到端实测工具**（2026-10-17 链 AK 建立）。

用途：在没有真 API key 的情况下，把 DPIM 的 **Anthropic Messages 协议路径**整条跑通，
并可注入失败来验证「降级 → 恢复 → 自动补偿」与「失败可见」。

它做三件事：
1. `POST /v1/messages` —— 按请求里 `output_schema` 的**属性名**判断是哪个角色
   （`{raw_content,chunks}`=In / `new_nodes`=Gr / `summary`=Cr / `verdict`=Meta），
   回一个能过 Pydantic 校验的最小对象；每个请求（含鉴权头 / max_tokens / thinking /
   temperature）追加写进同目录的 `anthropic-stub-requests.jsonl`，便于事后核对**请求到底长什么样**。
2. `GET /v1/models` —— 给 `POST /settings/models` 与**健康检查**用（Anthropic 形状 + `data[].id`）。
3. `POST /__fail_next {"n":20,"status":401}` —— 注入失败：`status>=500` 属可重试类（事件回
   `indexed` 等补偿）、`4xx` 属判死（事件 `failed` 并把原文写进 `error`）；`{"n":0}` 取消注入。

## 怎么用（隔离跑，别碰真实库）

```powershell
# 1) 起桩
dpim\.venv\Scripts\python.exe dpim\tests\tools\anthropic_stub.py 8799
# 2) 起隔离后端（数据/配置/日志全在 %TEMP%，端口避开常用的 8000）
$root = 'C:\Users\Lenovo\AppData\Local\Temp\dpim-e2e'
$env:DPIM_MEMORY_DB_PATH="$root\memory.db"; $env:DPIM_GRAPH_JSON_PATH="$root\graph.json"
$env:DPIM_LOG_DIR="$root\logs";             $env:DPIM_CONFIG_FILE="$root\dpim.json"
$env:DPIM_PROVIDERS='{"stub":{"base_url":"http://127.0.0.1:8799/v1","api_key":"stub-key","models":["stub-claude-4"],"format":"anthropic","thinking_budget":2048}}'
$env:DPIM_ACTIVE_PROVIDER='stub'; $env:DPIM_AGENT_MODE='pipeline'; $env:DPIM_AGENT_CR_SKIP_CHARS='0'
$env:DPIM_HEALTH_CHECK_INTERVAL='5'; $env:DPIM_COMPENSATE_CHECK_INTERVAL='2'
dpim\.venv\Scripts\python.exe dpim\main.py serve --port 8123     # workdir=dpim
# 3) 跑：POST /ingest → GET /events/{id}（linked）→ GET /nodes（有节点）
# 4) 注入失败 → 看 /health 的 status/degraded 与 events 的 error 字段
```

> 隔离要点：`DPIM_MEMORY_DB_PATH` 决定数据根（`repos/index.json` 也随之落到临时目录），
> `DPIM_CONFIG_FILE` 让后端**完全不读不写**真实 `dpim.json`——实测期间真实库零改动。
> 桩的**证据**在 JSONL 日志里：`x_api_key` / `anthropic_version` / `max_tokens` / `thinking` /
> `has_temperature` / `system_is_top_level` 逐条可查（本轮就是靠它抓出「健康检查发 Bearer」）。
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anthropic-stub-requests.jsonl")
FAIL_NEXT = {"n": 0, "status": 503}
CALLS = {"n": 0}


def synthesize(user: dict) -> dict:
    """按 output_schema 的属性名判断角色，合成一个能过校验的最小返回。"""
    props = set((user.get("output_schema") or {}).get("properties") or {})
    if {"raw_content", "chunks"} <= props:
        raw = user.get("raw_content") or ""
        chunk = raw[:24]
        chunks = (
            [{"content": chunk, "chunk_type": "data", "label": "桩分块", "confidence": 0.9}]
            if chunk
            else []
        )
        return {"raw_content": raw, "chunks": chunks}
    if "new_nodes" in props:
        quote = ""
        for c in user.get("chunks") or []:
            quote = (c or {}).get("content") or ""
            if quote:
                break
        nodes = (
            [{
                "title": "桩节点：端到端实测",
                "content": quote,
                "node_type": "data",
                "confidence": 0.9,
                "evidence_quote": quote,  # 必须是原文子串（元认知的本地检查会验来源锚定）
            }]
            if quote
            else []
        )
        return {"new_nodes": nodes, "new_edges": []}
    if "summary" in props:
        return {
            "summary": ["桩概括：一条用于端到端实测的事件"],
            "themes": ["端到端实测"],
            "confidence": 0.9,
        }
    if "verdict" in props:
        return {"verdict": "pass", "issues": []}
    if "method" in props:
        return {"method": "hybrid", "keywords": ["桩"], "confidence": 0.9}
    raise ValueError(f"桩无法识别角色，schema 属性={sorted(props)}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音默认访问日志
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._record("GET", None)
            self._send(200, {
                "data": [
                    {"id": "stub-claude-4", "display_name": "Stub Claude 4", "type": "model"},
                    {"id": "stub-claude-mini", "display_name": "Stub Claude Mini", "type": "model"},
                ],
                "has_more": False,
                "first_id": "stub-claude-4",
                "last_id": "stub-claude-mini",
            })
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        if self.path.rstrip("/").endswith("/__fail_next"):
            spec = json.loads(raw or "{}") or {}
            FAIL_NEXT["n"] = int(spec.get("n") or 1)
            FAIL_NEXT["status"] = int(spec.get("status") or 503)
            self._send(200, {"fail_next": FAIL_NEXT["n"], "status": FAIL_NEXT["status"]})
            return
        try:
            body = json.loads(raw or "{}")
        except Exception:
            self._send(400, {"error": "bad json"})
            return
        self._record("POST", body)
        if FAIL_NEXT["n"] > 0:
            FAIL_NEXT["n"] -= 1
            code = FAIL_NEXT.get("status") or 503
            kind = "overloaded_error" if code >= 500 else "authentication_error"
            self._send(code, {"type": "error", "error": {
                "type": kind,
                "message": f"桩注入的 {code}（{'可重试' if code >= 500 else '不可重试/判死'}）",
            }})
            return
        try:
            user_text = ""
            for m in reversed(body.get("messages") or []):
                if m.get("role") == "user":
                    user_text = m.get("content") or ""
                    break
            user = json.loads(user_text) if user_text.strip().startswith("{") else {}
            payload = synthesize(user)
        except Exception as exc:  # 桩自己出错也要看得见
            self._send(500, {"type": "error", "error": {"type": "stub_error", "message": str(exc)}})
            return
        CALLS["n"] += 1
        self._send(200, {
            "id": f"msg_stub_{CALLS['n']}",
            "type": "message",
            "role": "assistant",
            "model": body.get("model") or "stub",
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        })

    def _record(self, method: str, body: dict | None) -> None:
        row = {
            "method": method,
            "path": self.path,
            "x_api_key": self.headers.get("x-api-key"),
            "anthropic_version": self.headers.get("anthropic-version"),
            "authorization": self.headers.get("authorization"),
            "fail_next": FAIL_NEXT["n"],
            "body_keys": sorted((body or {}).keys()),
            "max_tokens": (body or {}).get("max_tokens"),
            "thinking": (body or {}).get("thinking"),
            "has_temperature": "temperature" in (body or {}),
            "temperature": (body or {}).get("temperature"),
            "system_is_top_level": isinstance((body or {}).get("system"), str),
            "system_head": ((body or {}).get("system") or "")[:60],
        }
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"stub listening on http://127.0.0.1:{port}  log={LOG_PATH}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
