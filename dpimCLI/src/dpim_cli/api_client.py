"""HTTP 客户端 — 封装 DPIM 后端全部 REST API。"""

import httpx


def repo_params(repo_id: str = "", repo_ids: list[str] | None = None) -> dict:
    """库作用域查询参数（v1.29/v1.30）：单库 `repo_id` / 联查 `repo_ids=a,b`。

    空值一律不出现在查询串里（后端对缺省 `repo_id` 取**活动库**，
    对缺省 `repo_ids` 取全部受管库——显式传空串反而会踩到 404/422）。
    """
    params: dict[str, str] = {}
    if repo_id:
        params["repo_id"] = repo_id
    if repo_ids:
        joined = ",".join(x for x in repo_ids if x)
        if joined:
            params["repo_ids"] = joined
    return params


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

    def _post(self, path: str, json: dict | None = None,
              params: dict | None = None) -> dict:
        return self._request("POST", path, json=json or {}, params=params)

    def _put(self, path: str, json: dict | None = None) -> dict:
        return self._request("PUT", path, json=json or {})

    def _delete(self, path: str, json: dict | None = None,
                params: dict | None = None) -> dict:
        return self._request("DELETE", path, json=json, params=params)

    # ── 系统状态 ──

    def health(self) -> dict:
        """GET /health 系统健康状态。"""
        return self._get("/health")

    def state_key(self) -> dict:
        """GET /state-hash 状态校验密钥。"""
        return self._get("/state-hash")

    # ── 事件管理 ──

    def ingest(self, content: str, event_type: str = "interaction",
               repo_id: str = "") -> dict:
        """POST /ingest 写入事件（`repo_id` 指定目标库，缺省活动库）。"""
        body: dict = {"content": content, "event_type": event_type}
        if repo_id:
            body["repo_id"] = repo_id
        return self._post("/ingest", body)

    def list_events(self, type: str = "", status: str = "",
                    limit: int = 20, offset: int = 0,
                    repo_id: str = "", repo_ids: list[str] | None = None) -> dict:
        """GET /events 分页事件列表（单库 `repo_id` / 联查 `repo_ids`）。"""
        params = {"limit": limit, "offset": offset, **repo_params(repo_id, repo_ids)}
        if type:
            params["type"] = type
        if status:
            params["status"] = status
        return self._get("/events", params)

    def get_event(self, event_id: str, repo_id: str = "") -> dict:
        """GET /events/{id} 事件详情（跨库跳转必须带 repo_id，否则 404）。"""
        return self._get(f"/events/{event_id}", repo_params(repo_id) or None)

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

    def list_nodes(self, type: str = "", limit: int = 20, offset: int = 0,
                   repo_id: str = "", repo_ids: list[str] | None = None) -> dict:
        """GET /nodes 分页节点列表（单库 `repo_id` / 联查 `repo_ids`）。"""
        params = {"limit": limit, "offset": offset, **repo_params(repo_id, repo_ids)}
        if type:
            params["type"] = type
        return self._get("/nodes", params)

    def get_node(self, node_id: str, repo_id: str = "") -> dict:
        """GET /nodes/{id} 节点详情（含关联边）。"""
        return self._get(f"/nodes/{node_id}", repo_params(repo_id) or None)

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

    def list_edges(self, node_id: str = "", source: str = "", target: str = "",
                   relation: str = "", limit: int = 200, offset: int = 0,
                   repo_id: str = "", repo_ids: list[str] | None = None) -> dict:
        """GET /edges 边列表（v1.37）：`node_id` 两侧命中；按 (source,target) 稳定排序。"""
        params = {"limit": limit, "offset": offset, **repo_params(repo_id, repo_ids)}
        for key, value in (("node_id", node_id), ("source", source),
                           ("target", target), ("relation", relation)):
            if value:
                params[key] = value
        return self._get("/edges", params)

    # ── 检索与反馈 ──

    def search(self, query: str, source_filter: str = "all",
               max_hops: int = 2, limit: int = 20, offset: int = 0,
               repo_ids: list[str] | None = None) -> dict:
        """POST /query 混合检索（`repo_ids` 单库 = 指定库，多库 = 联合检索）。"""
        body = {
            "query": query,
            "source_filter": source_filter,
            "max_hops": max_hops,
            "limit": limit,
            "offset": offset,
        }
        if repo_ids:
            body["repo_ids"] = [x for x in repo_ids if x]
        return self._post("/query", body)

    def feedback(self, result_id: str, accepted: bool, repo_id: str = "") -> dict:
        """POST /feedback 检索结果反馈（跨库结果必须带 `repo_id`，否则落在活动库）。"""
        body: dict = {"result_id": result_id, "accepted": accepted}
        if repo_id:
            body["repo_id"] = repo_id
        return self._post("/feedback", body)

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

    # ── 库管理（v1.29+，11 个端点）────────────────────────────────────────────

    def list_repos(self) -> dict:
        """GET /repos 库登记列表。"""
        return self._get("/repos")

    def get_repo(self, repo_id: str) -> dict:
        """GET /repos/{id} 库详情（含状态分布）。"""
        return self._get(f"/repos/{repo_id}")

    def create_repo(self, name: str, group: str = "", note: str = "",
                    root: str = "", root_kind: str = "managed") -> dict:
        """POST /repos 建库（managed 落分组目录；external 登记既有目录）。"""
        body: dict = {"name": name, "root_kind": root_kind}
        if group:
            body["group"] = group
        if note:
            body["note"] = note
        if root:
            body["root"] = root
        return self._post("/repos", body)

    def adopt_repo(self, root: str, name: str = "", group: str = "",
                   adopt_missing: bool = True) -> dict:
        """POST /repos/adopt 收养既有目录（缺件按 adopt_missing 决定补空还是 400）。"""
        body: dict = {"root": root, "adopt_missing": adopt_missing}
        if name:
            body["name"] = name
        if group:
            body["group"] = group
        return self._post("/repos/adopt", body)

    def rebuild_repos(self) -> dict:
        """POST /repos/rebuild 重建登记表（坏索引恢复；绝不删数据文件）。"""
        return self._post("/repos/rebuild")

    def purge_repo(self, repo_id: str) -> dict:
        """POST /repos/{id}/purge 清除书目（先整库备份，再删库文件）。"""
        return self._post(f"/repos/{repo_id}/purge")

    def update_repo(self, repo_id: str, **fields) -> dict:
        """PUT /repos/{id} 改库信息 / 受管开关 / 外部库重指向（root）。"""
        return self._put(f"/repos/{repo_id}", fields)

    def delete_repo(self, repo_id: str) -> dict:
        """DELETE /repos/{id} 摘除登记（不删磁盘文件）。"""
        return self._delete(f"/repos/{repo_id}")

    def activate_repo(self, repo_id: str) -> dict:
        """POST /repos/{id}/activate 切换活动库。"""
        return self._post(f"/repos/{repo_id}/activate")

    def generate_repo(self, repo_id: str) -> dict:
        """POST /repos/{id}/generate 库级联合生成知识（该库全部待构图事件入队）。"""
        return self._post(f"/repos/{repo_id}/generate")

    def refresh_repo(self, repo_id: str) -> dict:
        """POST /repos/{id}/refresh 显式刷新/修复一个库（对账源证 → 脏则落盘）。"""
        return self._post(f"/repos/{repo_id}/refresh")

    # ── 存储维护（v1.30，5 个端点）──────────────────────────────────────────

    def maintenance_backup(self, note: str = "", repo_id: str = "") -> dict:
        """POST /maintenance/backup 整库备份（VACUUM INTO + graph.json + manifest）。"""
        params = repo_params(repo_id)
        if note:
            params["note"] = note
        return self._post("/maintenance/backup", params=params or None)

    def maintenance_backups(self, repo_id: str = "") -> dict:
        """GET /maintenance/backups 列出整库备份（新到旧）。"""
        return self._get("/maintenance/backups", repo_params(repo_id) or None)

    def maintenance_verify(self, repo_id: str = "") -> dict:
        """POST /maintenance/verify 只读一致性校验。"""
        return self._post("/maintenance/verify", params=repo_params(repo_id) or None)

    def maintenance_ops(self, limit: int = 100, offset: int = 0,
                        repo_id: str = "") -> dict:
        """GET /maintenance/ops 图层操作日志（审计）。"""
        params = {"limit": limit, "offset": offset, **repo_params(repo_id)}
        return self._get("/maintenance/ops", params)

    def maintenance_checkpoint(self, repo_id: str = "") -> dict:
        """POST /maintenance/checkpoint WAL 检查点（TRUNCATE）。"""
        return self._post("/maintenance/checkpoint", params=repo_params(repo_id) or None)

    # ── 本地日志与回收站（v1.31）────────────────────────────────────────────

    def logs(self, kind: str = "backend", date: str = "", level: str = "",
             keyword: str = "", tail: int = 200) -> dict:
        """GET /logs 翻看本地日志尾部（按通道/日期/级别/关键词）。"""
        params: dict = {"kind": kind, "tail": tail}
        for key, value in (("date", date), ("level", level), ("keyword", keyword)):
            if value:
                params[key] = value
        return self._get("/logs", params)

    def trash_list(self, repo_id: str = "") -> dict:
        """GET /trash 回收站留档清单。"""
        return self._get("/trash", repo_params(repo_id) or None)

    def trash_restore(self, kind: str, item_id: str, repo_id: str = "") -> dict:
        """POST /trash/restore 从留档恢复（事件/节点按原 id 重新入库）。"""
        return self._post(
            "/trash/restore",
            {"kind": kind, "id": item_id},
            params=repo_params(repo_id) or None,
        )

    # ── Agent 运维（3 个端点）──────────────────────────────────────────────

    def agent_logs(self, limit: int = 50, full: bool = False) -> dict:
        """GET /agent/logs AI 调用日志（环形缓冲，新→旧）。"""
        params: dict = {"limit": limit}
        if full:
            params["full"] = "true"
        return self._get("/agent/logs", params)

    def agent_compensate(self, repo_id: str = "") -> dict:
        """POST /agent/compensate 手动触发补偿（积压 raw/indexed 事件重入队）。"""
        return self._post("/agent/compensate", params=repo_params(repo_id) or None)

    def agent_maintain(self, mode: str = "update", repo_id: str = "") -> dict:
        """POST /agent/maintain 手动触发图维护（mode: update 两阶段 / compress 删繁就简）。"""
        return self._post(
            "/agent/maintain",
            {"mode": mode},
            params=repo_params(repo_id) or None,
        )

    # ── 配置探测（v1.34）──────────────────────────────────────────────────

    def probe_models(self, provider: str, base_url: str = "",
                     api_key: str = "") -> dict:
        """POST /settings/models 联网探测某提供商的模型列表（失败放 error，不报 4xx）。"""
        body: dict = {"provider": provider}
        if base_url:
            body["base_url"] = base_url
        if api_key:
            body["api_key"] = api_key
        return self._post("/settings/models", body)
