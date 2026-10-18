"""`POST /agent/maintain` 请求体测试（v1.32）：`mode` 传递真缺陷修复。

修复前该端点**完全不读 body**，payload 恒为 `{}` → orchestrator 的
`payload.get("mode")` 永远为 None →「前端选 update 实际走 compress」，
链 Q18 的两阶段结构优化只有 `^update` 指令一条路可达。

这里用假 orchestrator **截获 enqueue 的 QueueMessage 并断言 payload**
（不是只断言 200）——否则「端点收下了参数但没传下去」这类缺陷测不出来。
"""

import pytest
from fastapi.testclient import TestClient

from interface import api, deps


class _FakeOrchestrator:
    """只截获 enqueue，不启动 worker：断言的是「端点往队列里放了什么」。"""

    def __init__(self) -> None:
        self.messages: list = []

    async def enqueue(self, message) -> None:
        self.messages.append(message)


@pytest.fixture
def maintain_env():
    fake = _FakeOrchestrator()
    deps.orchestrator = fake
    deps.repos = None
    deps.graph_store = None
    yield TestClient(api.app), fake
    deps.orchestrator = None


class TestMaintainMode:
    def test_default_mode_is_update(self, maintain_env):
        """不传 body：默认 update（两阶段结构优化），队列类型 maintain_graph。"""
        client, fake = maintain_env
        resp = client.post("/agent/maintain")
        assert resp.status_code == 200
        assert len(fake.messages) == 1
        message = fake.messages[0]
        assert message.type == "maintain_graph"
        assert message.payload["mode"] == "update"
        assert "mode=update" in resp.json()["message"]

    def test_explicit_compress_mode(self, maintain_env):
        client, fake = maintain_env
        resp = client.post("/agent/maintain", json={"mode": "compress"})
        assert resp.status_code == 200
        assert fake.messages[0].payload["mode"] == "compress"

    def test_empty_body_object_defaults_to_update(self, maintain_env):
        client, fake = maintain_env
        assert client.post("/agent/maintain", json={}).status_code == 200
        assert fake.messages[0].payload == {"mode": "update"}

    def test_invalid_mode_rejected_422_and_not_enqueued(self, maintain_env):
        client, fake = maintain_env
        resp = client.post("/agent/maintain", json={"mode": "bogus"})
        assert resp.status_code == 422  # Literal 枚举校验
        assert fake.messages == []

    def test_repo_id_query_rides_along_with_mode(self, maintain_env):
        client, fake = maintain_env
        resp = client.post(
            "/agent/maintain", params={"repo_id": "rp_other"}, json={"mode": "compress"}
        )
        assert resp.status_code == 200
        assert fake.messages[0].payload == {"mode": "compress", "repo_id": "rp_other"}

    def test_missing_orchestrator_503(self, maintain_env):
        client, _fake = maintain_env
        deps.orchestrator = None
        assert client.post("/agent/maintain").status_code == 503
