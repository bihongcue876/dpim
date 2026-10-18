"""多库联合检索与库作用域测试（v1.30）。

覆盖此前的静默缺陷：

- 联合检索**双重分页**（limit/offset 传给每库、融合后又切一次）→ 第二页错乱、total 失真
- 联合检索无**融合轨迹**（说不清某条结果为什么排在这里、来自哪些库）
- 事件原文/知识节点模式选「全部受管库」时**静默退化为活动库**
- `/feedback`、`GET /events/{id}`、`^指令`、`/agent/*` **忽略库作用域**
"""

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.models import GraphEdge, GraphNode, NodeMetadata, NodeType, SourceRef
from core.repos import DEFAULT_REPO_ID, RepoManager
from interface import api, deps


def _node(node_id: str, title: str, node_type: NodeType = NodeType.interaction) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        title=title,
        content="内容",
        node_type=node_type,
        confidence=0.5,
        source_refs=[SourceRef(event_id="e1", valid=True, hash="h")],
        metadata=NodeMetadata(evidence_quote="内容"),
    )


@pytest.fixture
def joint_env(db, event_store, graph_store, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "memory_db_path", str(tmp_path / "memory.db"))
    monkeypatch.setattr(settings, "graph_json_path", str(tmp_path / "graph.json"))
    deps.db = db
    deps.event_store = event_store
    deps.graph_store = graph_store
    mgr = RepoManager()
    mgr.bind_default(db, event_store, graph_store)
    deps.repos = mgr
    yield TestClient(api.app), mgr, tmp_path
    deps.repos = None


async def _seed(mgr, repo_id: str, text: str) -> str:
    eid, _status = await mgr.entries[repo_id].event_store.insert_event(text, "data")
    return eid


async def _two_repos(mgr) -> tuple[str, str]:
    await mgr.initialize()
    first = await mgr.create_repo("库一")
    second = await mgr.create_repo("库二")
    return first.repo_id, second.repo_id


class TestJointPagination:
    @pytest.mark.asyncio
    async def test_pages_are_disjoint_and_total_is_fused_count(self, joint_env):
        client, mgr, _tmp = joint_env
        repo_a, repo_b = await _two_repos(mgr)
        for i in range(8):
            await _seed(mgr, repo_a, f"kubernetes 集群甲 {i}")
            await _seed(mgr, repo_b, f"kubernetes 集群乙 {i}")

        body = {"query": "kubernetes", "repo_ids": [repo_a, repo_b], "limit": 5}
        page1 = client.post("/query", json={**body, "offset": 0}).json()
        page2 = client.post("/query", json={**body, "offset": 5}).json()

        assert page1["total"] == page2["total"] == 16  # 融合去重后的真实总数
        first = {r["node_id"] for r in page1["results"]}
        second = {r["node_id"] for r in page2["results"]}
        assert len(first) == 5 and len(second) == 5
        assert not (first & second)  # 双重分页会让第二页重复或漏项

    @pytest.mark.asyncio
    async def test_identical_content_deduped_across_repos(self, joint_env):
        client, mgr, _tmp = joint_env
        repo_a, repo_b = await _two_repos(mgr)
        await _seed(mgr, repo_a, "kubernetes 同一条内容")
        await _seed(mgr, repo_b, "kubernetes 同一条内容")

        data = client.post(
            "/query", json={"query": "kubernetes", "repo_ids": [repo_a, repo_b]}
        ).json()
        assert data["total"] == 1  # content_hash 去重
        assert data["trace"]["deduped"] == 1
        assert len(data["results"][0]["source_repos"]) == 2  # 来源库锚定保留两库


class TestJointTrace:
    @pytest.mark.asyncio
    async def test_trace_reports_pool_repos_and_contributions(self, joint_env):
        client, mgr, _tmp = joint_env
        repo_a, repo_b = await _two_repos(mgr)
        await _seed(mgr, repo_a, "kubernetes 甲")
        await _seed(mgr, repo_b, "kubernetes 乙")

        data = client.post(
            "/query",
            json={"query": "kubernetes", "repo_ids": [repo_a, repo_b], "limit": 10},
        ).json()
        trace = data["trace"]
        assert trace is not None
        assert trace["candidate_pool"] >= 50  # 每库取候选池，不是只取最终页
        assert {t["repo_id"] for t in trace["per_repo"]} == {repo_a, repo_b}
        assert all(t["candidates"] > 0 for t in trace["per_repo"])
        assert trace["hits"], "轨迹应包含本页每条结果"
        top = trace["hits"][0]
        assert top["contributions"], "每条结果要有在各库的排名/原始分/RRF 明细"
        assert {"repo_id", "rank", "score", "rrf"} <= set(top["contributions"][0])

    def test_single_repo_search_has_no_trace(self, joint_env):
        client, _mgr, _tmp = joint_env
        data = client.post("/query", json={"query": "kubernetes"}).json()
        assert data["trace"] is None


class TestJointLists:
    @pytest.mark.asyncio
    async def test_events_joint_list_spans_repos(self, joint_env):
        client, mgr, _tmp = joint_env
        repo_a, repo_b = await _two_repos(mgr)
        first = await _seed(mgr, repo_a, "库一的事件")
        second = await _seed(mgr, repo_b, "库二的事件")

        resp = client.get(
            "/events", params={"repo_ids": f"{repo_a},{repo_b}", "limit": 50}
        )
        assert resp.status_code == 200
        ids = {item["event_id"] for item in resp.json()["items"]}
        assert {first, second} <= ids

    @pytest.mark.asyncio
    async def test_nodes_joint_list_spans_repos(self, joint_env):
        client, mgr, _tmp = joint_env
        repo_a, repo_b = await _two_repos(mgr)
        graph_a = mgr.entries[repo_a].graph_store
        graph_b = mgr.entries[repo_b].graph_store
        graph_a.add_node(_node("n_a", "库一要点"))
        graph_b.add_node(_node("n_b", "库二要点"))
        await graph_a.save()
        await graph_b.save()

        resp = client.get(
            "/nodes", params={"repo_ids": f"{repo_a},{repo_b}", "limit": 50}
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        ids = {item["node_id"] for item in items}
        assert {"n_a", "n_b"} <= ids
        # node_type 必须是**值文本**：联合路径此前写成 str(枚举) → "NodeType.interaction"，
        # 与单库路径（"interaction"）不一致 → 前端「全部书目」下按类型筛选全部失配
        assert {item["node_type"] for item in items} == {"interaction"}

    def test_unknown_repo_in_joint_list_rejected(self, joint_env):
        client, _mgr, _tmp = joint_env
        resp = client.get("/events", params={"repo_ids": "rp_nope"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_edges_joint_list_spans_repos_with_ownership(self, joint_env):
        """GET /edges（v1.37）联合列表：跨库取边 + 来源库归属。"""
        client, mgr, _tmp = joint_env
        repo_a, repo_b = await _two_repos(mgr)
        graph_a = mgr.entries[repo_a].graph_store
        graph_b = mgr.entries[repo_b].graph_store
        for nid, title in (("n_a1", "甲一"), ("n_a2", "甲二")):
            graph_a.add_node(_node(nid, title))
        for nid, title in (("n_b1", "乙一"), ("n_b2", "乙二")):
            graph_b.add_node(_node(nid, title))
        graph_a.add_edge(GraphEdge(
            source="n_a1", target="n_a2", relation="甲内", evidence_event_id="e1"
        ))
        graph_b.add_edge(GraphEdge(
            source="n_b1", target="n_b2", relation="乙内", evidence_event_id="e1"
        ))
        await graph_a.save()
        await graph_b.save()

        resp = client.get(
            "/edges", params={"repo_ids": f"{repo_a},{repo_b}", "limit": 50}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert {e["source"]: e["repo_id"] for e in data["items"]} == {
            "n_a1": repo_a,
            "n_b1": repo_b,
        }
        assert {e["repo_name"] for e in data["items"]} == {"库一", "库二"}

    @pytest.mark.asyncio
    async def test_duplicate_edges_deduped_across_repos(self, joint_env):
        """同一份图层被复制成两个库 → 联合边列表只留首命中库的一条（与节点去重同纪律）。"""
        client, mgr, _tmp = joint_env
        repo_a, repo_b = await _two_repos(mgr)
        for repo_id in (repo_a, repo_b):
            gs = mgr.entries[repo_id].graph_store
            gs.add_node(_node("n_dup1", "同源一"))
            gs.add_node(_node("n_dup2", "同源二"))
            gs.add_edge(GraphEdge(
                source="n_dup1", target="n_dup2", relation="同一条", evidence_event_id="e1"
            ))
            await gs.save()

        data = client.get(
            "/edges", params={"repo_ids": f"{repo_a},{repo_b}", "limit": 50}
        ).json()
        assert data["total"] == 1
        assert data["items"][0]["repo_id"] == repo_a

    def test_edges_scope_errors(self, joint_env):
        """未知库：单库作用域 404、联合列表 422（与 /nodes 同语义）。"""
        client, _mgr, _tmp = joint_env
        assert client.get("/edges", params={"repo_id": "rp_nope"}).status_code == 404
        assert client.get("/edges", params={"repo_ids": "rp_nope"}).status_code == 422


class TestRepoScopeThreading:
    @pytest.mark.asyncio
    async def test_feedback_targets_given_repo(self, joint_env):
        client, mgr, _tmp = joint_env
        repo_a, _repo_b = await _two_repos(mgr)
        graph_a = mgr.entries[repo_a].graph_store
        graph_a.add_node(_node("n_target", "可反馈要点"))
        await graph_a.save()

        resp = client.post(
            "/feedback",
            json={"result_id": "n_target", "accepted": True, "repo_id": repo_a},
        )
        assert resp.status_code == 200
        assert resp.json()["confidence"] > 0.5  # 落在指定库，而不是活动库

    @pytest.mark.asyncio
    async def test_event_detail_respects_repo_scope(self, joint_env):
        client, mgr, _tmp = joint_env
        repo_a, repo_b = await _two_repos(mgr)
        event_id = await _seed(mgr, repo_b, "库二的事件详情")

        assert client.get(f"/events/{event_id}").status_code == 404  # 活动库里没有
        ok = client.get(f"/events/{event_id}", params={"repo_id": repo_b})
        assert ok.status_code == 200
        assert ok.json()["event_id"] == event_id
        assert repo_a  # 只为保持两库都已建

    @pytest.mark.asyncio
    async def test_command_respects_repo_scope(self, joint_env):
        client, mgr, _tmp = joint_env
        repo_a, _repo_b = await _two_repos(mgr)

        resp = client.post(
            "/ingest",
            json={
                "content": "^data 指定库的存储内容",
                "event_type": "data",
                "repo_id": repo_a,
            },
        )
        assert resp.status_code == 200
        # store 类指令确实创建了事件 → command_triggered 保持 False（前端按普通事件显示）
        assert "指令" in resp.json()["message"]
        assert await mgr.entries[repo_a].event_store.total_events() == 1
        assert await mgr.entries[DEFAULT_REPO_ID].event_store.total_events() == 0

    def test_maintain_accepts_repo_scope(self, joint_env):
        """维护端点接受库参数：此前忽略它，多库环境下总是打在活动库上。"""
        client, mgr, _tmp = joint_env
        resp = client.post("/agent/maintain", params={"repo_id": DEFAULT_REPO_ID})
        # orchestrator 未启动（TestClient 不触发 lifespan）→ 503 属预期，
        # 这里只断言参数被接受（不是 422 参数错误）
        assert resp.status_code in (200, 503)
