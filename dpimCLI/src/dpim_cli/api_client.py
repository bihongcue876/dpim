"""HTTP 客户端 — 封装 DPIM 后端全部 REST API。"""

import httpx


class DPIMError(Exception):
    """API 返回的错误。"""
    def __init__(self, code: str, message: str, status_code: int = 0):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"[{code}] {message}")


class ConnectionError(DPIMError):
    """网络连接失败。"""
    pass


class DPIMClient:
    """DPIM 后端 HTTP 客户端。"""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    # ── 底层请求 ──

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        try:
            r = self._client.request(method, url, **kwargs)
        except httpx.RequestError as e:
            raise ConnectionError("CONNECTION", f"无法连接到 {url}: {e}")

        try:
            body = r.json()
        except Exception:
            body = {}

        if not r.is_success:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            code = err.get("code", f"HTTP_{r.status_code}")
            # 后端 FastAPI 错误信封为 {detail: "..."}（422 时为校验错误数组），
            # 兼容 {error:{code,message}} 与 {message}；均缺省时退回 reason_phrase
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, list):  # FastAPI 422 校验错误 [{loc,msg,type},...]
                detail = "; ".join(
                    str(d.get("msg", d)) if isinstance(d, dict) else str(d)
                    for d in detail
                )
            msg = (
                err.get("message")
                or (str(detail) if detail else None)
                or body.get("message")
                or r.reason_phrase
                or str(r.status_code)
            )
            raise DPIMError(code, msg, r.status_code)

        return body

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json: dict | None = None) -> dict:
        return self._request("POST", path, json=json or {})

    def _put(self, path: str, json: dict | None = None) -> dict:
        return self._request("PUT", path, json=json or {})

    def _delete(self, path: str, json: dict | None = None) -> dict:
        return self._request("DELETE", path, json=json)

    # ── 系统状态 ──

    def health(self) -> dict:
        """GET /health 系统健康状态。"""
        return self._get("/health")

    def state_key(self) -> dict:
        """GET /state-hash 状态校验密钥。"""
        return self._get("/state-hash")

    # ── 事件管理 ──

    def ingest(self, content: str, event_type: str = "interaction") -> dict:
        """POST /ingest 写入事件。"""
        return self._post("/ingest", {"content": content, "event_type": event_type})

    def list_events(self, type: str = "", status: str = "",
                    limit: int = 20, offset: int = 0) -> dict:
        """GET /events 分页事件列表。"""
        params = {"limit": limit, "offset": offset}
        if type:
            params["type"] = type
        if status:
            params["status"] = status
        return self._get("/events", params)

    def get_event(self, event_id: str) -> dict:
        """GET /events/{id} 事件详情。"""
        return self._get(f"/events/{event_id}")

    def edit_event(self, event_id: str, content: str) -> dict:
        """PUT /events/{id} 修订事件 raw_content。"""
        return self._put(f"/events/{event_id}", {"content": content})

    def update_event_status(self, event_id: str, status: str) -> dict:
        """PUT /events/{id}/status 修改事件状态。"""
        return self._put(f"/events/{event_id}/status", {"status": status})

    def delete_event(self, event_id: str) -> dict:
        """DELETE /events/{id} 删除事件。"""
        return self._delete(f"/events/{event_id}")

    # ── 节点管理 ──

    def list_nodes(self, type: str = "", limit: int = 20, offset: int = 0) -> dict:
        """GET /nodes 分页节点列表。"""
        params = {"limit": limit, "offset": offset}
        if type:
            params["type"] = type
        return self._get("/nodes", params)

    def get_node(self, node_id: str) -> dict:
        """GET /nodes/{id} 节点详情（含关联边）。"""
        return self._get(f"/nodes/{node_id}")

    def create_node(self, title: str, content: str = "",
                    source_event_id: str = "") -> dict:
        """POST /nodes 手动创建节点。"""
        body = {"title": title, "content": content}
        if source_event_id:
            body["source_event_id"] = source_event_id
        return self._post("/nodes", body)

    def edit_node(self, node_id: str, content: str) -> dict:
        """PUT /nodes/{id} 修改节点 content。"""
        return self._put(f"/nodes/{node_id}", {"content": content})

    def delete_node(self, node_id: str, force: bool = False) -> dict:
        """DELETE /nodes/{id} 删除节点。"""
        return self._delete(f"/nodes/{node_id}", {"force": force})

    # ── 边管理 ──

    def create_edge(self, source: str, target: str, relation: str,
                    evidence_event_id: str = "") -> dict:
        """POST /edges 创建关联边。"""
        body = {"source": source, "target": target, "relation": relation}
        if evidence_event_id:
            body["evidence_event_id"] = evidence_event_id
        return self._post("/edges", body)

    def delete_edge(self, source: str, target: str) -> dict:
        """DELETE /edges 删除关联边。"""
        return self._delete("/edges", params={"source": source, "target": target})

    # ── 检索与反馈 ──

    def search(self, query: str, source_filter: str = "all",
               max_hops: int = 2, limit: int = 20, offset: int = 0) -> dict:
        """POST /query 混合检索。"""
        body = {
            "query": query,
            "source_filter": source_filter,
            "max_hops": max_hops,
            "limit": limit,
            "offset": offset,
        }
        return self._post("/query", body)

    def feedback(self, result_id: str, accepted: bool) -> dict:
        """POST /feedback 检索结果反馈。"""
        return self._post("/feedback", {"result_id": result_id, "accepted": accepted})

    # ── 配置管理 ──

    def get_settings(self) -> dict:
        """GET /settings 获取全部配置项。"""
        return self._get("/settings")

    def update_settings(self, **kwargs) -> dict:
        """PUT /settings 批量更新配置项。"""
        return self._put("/settings", kwargs)

    # ── 图谱管理 ──

    def clear_graph(self) -> dict:
        """DELETE /graph 清空图谱。"""
        return self._delete("/graph")
