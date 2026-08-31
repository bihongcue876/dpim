"""对话指令系统测试（v1.21：仅 ^英文动词、空格分隔；其余一律普通文本落库）：

- parse_command 严格语法（^ 前缀 + 英文动词；/ 前缀、中文词、冒号、未知 ^词 → 非指令）
- POST /ingest 指令分发：
  - 语义层（^compress）：AI 可用 → 入队 maintain_graph（可带 scope）；AI 不可用 → 明示拒绝
  - 确定层（^merge/^delete/^node）：同步执行 + 硬规则（类型边界/删除保护/system 保护）
  - 存储类（^data 等）：显式类型写事件，AI 不可用也可用
  - ^help：返回用法说明，不动数据
- 被 ban 的形式（/compress、^压缩、^data: 内容）→ 普通文本正常落库
"""

import pytest
from fastapi.testclient import TestClient

from core.commands import parse_command, usage_text
from core.config import settings
from core.models import NodeType
from core.state import ai_state
from interface import api
from tests.factories import make_node


@pytest.fixture
def test_app(db, event_store, graph_store, monkeypatch):
    """同 test_integration 夹具 + 注入记录型 orchestrator 桩。"""
    api.db = db
    api.event_store = event_store
    api.graph_store = graph_store
    enqueued: list = []

    class _StubOrchestrator:
        async def enqueue(self, msg):
            enqueued.append(msg)

    monkeypatch.setattr(api, "orchestrator", _StubOrchestrator())
    client = TestClient(api.app)
    client.enqueued = enqueued  # type: ignore[attr-defined]
    return client


@pytest.fixture
def ai_on():
    """临时开启 AI 可用（测试后还原）。"""
    old = ai_state.available
    ai_state.available = True
    yield
    ai_state.available = old


# ── 解析器 ──


class TestParseCommand:
    def test_compress(self):
        cmd = parse_command("^compress")
        assert cmd and cmd.kind == "compress" and cmd.scope == ""

    def test_compress_scoped(self):
        cmd = parse_command("^compress d1")
        assert cmd and cmd.kind == "compress" and cmd.scope == "d1"

    def test_update(self):
        cmd = parse_command("^update")
        assert cmd and cmd.kind == "update" and cmd.scope == ""
        cmd = parse_command("^update n1")
        assert cmd and cmd.kind == "update" and cmd.scope == "n1"

    def test_merge(self):
        cmd = parse_command("^merge t1 s1")
        assert cmd and cmd.kind == "merge"
        assert (cmd.target_id, cmd.source_id) == ("t1", "s1")

    def test_delete(self):
        cmd = parse_command("^delete n1")
        assert cmd and cmd.kind == "delete" and cmd.node_id == "n1"

    def test_store_all_types(self):
        for word, etype in [
            ("data", "data"), ("interaction", "interaction"), ("source", "source"),
        ]:
            cmd = parse_command(f"^{word} Python 异步编程笔记")
            assert cmd and cmd.kind == "store", word
            assert cmd.event_type == etype
            assert cmd.content == "Python 异步编程笔记"

    def test_store_content_case_preserved(self):
        cmd = parse_command("^Data mixed CASE 内容")
        assert cmd and cmd.kind == "store" and cmd.content == "mixed CASE 内容"

    def test_node_system(self):
        cmd = parse_command("^node system 标题 | 正文内容")
        assert cmd and cmd.kind == "node"
        assert (cmd.title, cmd.content) == ("标题", "正文内容")

    def test_node_system_no_space_after_word(self):
        cmd = parse_command("^node system标题 | 正文")
        assert cmd and cmd.kind == "node" and cmd.hints  # system 须后跟空格

    def test_fullwidth_caret_and_pipe_normalized(self):
        cmd = parse_command("＾compress")
        assert cmd and cmd.kind == "compress"
        cmd = parse_command("＾node system 标题｜正文")
        assert cmd and cmd.kind == "node"
        assert (cmd.title, cmd.content) == ("标题", "正文")

    def test_help(self):
        cmd = parse_command("^help")
        assert cmd and cmd.kind == "help"

    def test_whitespace_padded(self):
        assert parse_command("  ^compress  \n") is not None

    def test_banned_slash_prefix_is_plain_text(self):
        """/ 前缀全部 ban：不是指令，落库为普通文本。"""
        assert parse_command("/compress") is None
        assert parse_command("／compress") is None

    def test_banned_chinese_word_is_plain_text(self):
        """中文指令词 ban：^压缩 不是指令。"""
        assert parse_command("^压缩") is None
        assert parse_command("^压缩 d1") is None
        assert parse_command("^合并 t1 s1") is None
        assert parse_command("^数据 内容") is None

    def test_banned_colon_separator_is_plain_text(self):
        """冒号不是分隔符：^data: 内容 不是指令。"""
        assert parse_command("^data: 内容") is None
        assert parse_command("^data:内容") is None

    def test_unknown_caret_word_is_plain_text(self):
        assert parse_command("^unknown x") is None
        assert parse_command("^maintain") is None
        assert parse_command("^") is None

    def test_plain_text_not_command(self):
        assert parse_command("聊聊 ^compress 的用法") is None
        assert parse_command("compress") is None  # 缺前缀
        assert parse_command("") is None
        assert parse_command("   ") is None

    def test_usage_errors_have_hints(self):
        assert parse_command("^data").hints
        assert parse_command("^merge t1").hints
        assert parse_command("^delete").hints
        assert parse_command("^node data x | y").hints  # 非 system
        assert parse_command("^node system 只有标题").hints

    def test_usage_text_lists_caret_forms(self):
        text = usage_text()
        assert "^compress" in text and "^merge" in text and "^data" in text
        assert "^help" in text


# ── 端点分发 ──


class TestCompressCommand:
    def test_refuses_when_ai_unavailable(self, test_app):
        """AI 不可用 → 明示拒绝，不入队（存储类指令不受影响）。"""
        resp = test_app.post("/ingest", json={"content": "^compress", "event_type": "interaction"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["command_triggered"] is True
        assert data["event_id"] == ""
        assert data["status"] == "skipped"
        assert "未执行" in data["message"]
        assert len(test_app.enqueued) == 0  # type: ignore[attr-defined]

    def test_no_candidates_reports_immediately(self, test_app, ai_on, monkeypatch):
        """无候选（全图足够简练）→ 不入队，立即明示「无需压缩」。

        保守全图压缩的正确结果必须可感知——否则用户以为指令失灵。"""
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        resp = test_app.post("/ingest", json={"content": "^compress", "event_type": "interaction"})
        data = resp.json()
        assert data["command_triggered"] is True
        assert "无需压缩" in data["message"]
        assert len(test_app.enqueued) == 0  # type: ignore[attr-defined]

    async def test_enqueues_maintain_graph_with_candidates(
        self, test_app, graph_store, ai_on, monkeypatch
    ):
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        await make_node(graph_store, "d1", "长资料", "冗" * 600)  # 冗长 → 压缩候选
        resp = test_app.post("/ingest", json={"content": "^compress", "event_type": "interaction"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["command_triggered"] is True
        assert data["event_id"] == ""
        assert "已入队" in data["message"] and "发现候选" in data["message"]
        assert len(test_app.enqueued) == 1  # type: ignore[attr-defined]
        msg = test_app.enqueued[0]  # type: ignore[attr-defined]
        assert msg.type == "maintain_graph"
        assert msg.payload == {}

    async def test_enqueues_scoped(self, test_app, graph_store, ai_on, monkeypatch):
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        await make_node(graph_store, "d1", "长资料", "冗" * 600)
        test_app.post("/ingest", json={"content": "^compress d1", "event_type": "data"})
        msg = test_app.enqueued[0]  # type: ignore[attr-defined]
        assert msg.payload == {"scope": "d1"}

    async def test_scoped_node_without_candidates(self, test_app, graph_store, ai_on, monkeypatch):
        """scope 节点存在但无相关候选（已连线、内容短）→ 即时明示，不入队。"""
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        await make_node(graph_store, "d1", "短资料", "内容", event_id="e1")
        await make_node(graph_store, "d2", "邻居", "内容", event_id="e2")
        from tests.factories import make_edge
        await make_edge(graph_store, "d1", "d2", event_id="e2")
        resp = test_app.post("/ingest", json={"content": "^compress d1", "event_type": "data"})
        msg = resp.json()["message"]
        assert "无需压缩" in msg and "d1" in msg
        assert len(test_app.enqueued) == 0  # type: ignore[attr-defined]

    async def test_enqueues_with_oversplit_candidates(
        self, test_app, graph_store, event_store, ai_on, monkeypatch
    ):
        """同源过碎（单事件 ≥6 节点）也触发压缩入队，消息报出候选类别。"""
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        eid, _ = await event_store.insert("一个被拆得很碎的事件", "data")
        for i in range(6):
            await make_node(graph_store, f"s{i}", f"碎片{i}", f"内容{i}", event_id=eid)
        resp = test_app.post("/ingest", json={"content": "^compress", "event_type": "interaction"})
        msg = resp.json()["message"]
        assert "已入队" in msg and "同源过碎 1" in msg
        assert len(test_app.enqueued) == 1  # type: ignore[attr-defined]

    def test_scoped_missing_node_refused(self, test_app, ai_on, monkeypatch):
        """范围压缩的限定节点不存在 → 入队前拦截（避免静默空转）。"""
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        resp = test_app.post("/ingest", json={"content": "^compress ghost", "event_type": "data"})
        assert "未执行" in resp.json()["message"]
        assert "ghost" in resp.json()["message"]
        assert len(test_app.enqueued) == 0  # type: ignore[attr-defined]


class TestUpdateCommand:
    """^update 图结构优化（v1.24）：两阶段——减碎+补缺 → 连线。"""

    def test_refuses_when_ai_unavailable(self, test_app):
        resp = test_app.post("/ingest", json={"content": "^update", "event_type": "interaction"})
        data = resp.json()
        assert data["command_triggered"] is True
        assert "未执行" in data["message"]
        assert len(test_app.enqueued) == 0  # type: ignore[attr-defined]

    async def test_enqueues_two_phase(self, test_app, graph_store, ai_on, monkeypatch):
        """有结构候选（孤立节点）→ 入队 payload mode=update，消息注明两阶段。"""
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        await make_node(graph_store, "iso1", "孤岛", "内容", event_id="e1")
        resp = test_app.post("/ingest", json={"content": "^update", "event_type": "interaction"})
        data = resp.json()
        assert data["command_triggered"] is True and data["event_id"] == ""
        assert "已入队" in data["message"] and "两阶段" in data["message"]
        msg = test_app.enqueued[0]  # type: ignore[attr-defined]
        assert msg.type == "maintain_graph"
        assert msg.payload == {"mode": "update"}

    async def test_enqueues_scoped(self, test_app, graph_store, ai_on, monkeypatch):
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        await make_node(graph_store, "iso1", "孤岛", "内容", event_id="e1")
        test_app.post("/ingest", json={"content": "^update iso1", "event_type": "data"})
        msg = test_app.enqueued[0]  # type: ignore[attr-defined]
        assert msg.payload == {"mode": "update", "scope": "iso1"}

    def test_no_candidates_reports_immediately(self, test_app, ai_on, monkeypatch):
        """无结构候选 → 立即「无需优化」，不入队。"""
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        resp = test_app.post("/ingest", json={"content": "^update", "event_type": "interaction"})
        data = resp.json()
        assert "无需优化" in data["message"]
        assert len(test_app.enqueued) == 0  # type: ignore[attr-defined]

    def test_scoped_missing_node_refused(self, test_app, ai_on, monkeypatch):
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        resp = test_app.post("/ingest", json={"content": "^update ghost", "event_type": "data"})
        assert "未执行" in resp.json()["message"] and "ghost" in resp.json()["message"]
        assert len(test_app.enqueued) == 0  # type: ignore[attr-defined]


class TestMergeCommand:
    async def test_merge_success(self, test_app, graph_store):
        await make_node(graph_store, "t1", "主题", "内容A", event_id="e1")
        await make_node(graph_store, "s1", "主题", "内容B", event_id="e2")
        resp = test_app.post(
            "/ingest",
            json={"content": "^merge t1 s1", "event_type": "interaction"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["command_triggered"] is True
        assert "已合并" in data["message"]
        assert graph_store.get_node("s1") is None
        t = graph_store.get_node("t1")
        assert "内容A" in t.content and "内容B" in t.content  # 内容合并不丢失
        assert {sr.event_id for sr in t.source_refs} == {"e1", "e2"}  # 源证并集
        # FTS：source 不可检索，target 可检索
        r = await graph_store.search_node_fts("内容B")
        assert any(x["node_id"] == "t1" for x in r)

    async def test_merge_type_mismatch_refused(self, test_app, graph_store):
        await make_node(graph_store, "t1", "资料", "内容", node_type=NodeType.data)
        await make_node(graph_store, "i1", "对话", "内容",
                        node_type=NodeType.interaction, event_id="e2")
        resp = test_app.post(
            "/ingest",
            json={"content": "^merge t1 i1", "event_type": "interaction"},
        )
        assert "未执行" in resp.json()["message"]
        assert graph_store.get_node("i1") is not None

    async def test_merge_system_refused(self, test_app, graph_store):
        await make_node(graph_store, "t1", "资料", "内容")
        await make_node(graph_store, "sys1", "系统", "内容", node_type=NodeType.system)
        resp = test_app.post(
            "/ingest",
            json={"content": "^merge t1 sys1", "event_type": "interaction"},
        )
        assert "system" in resp.json()["message"]
        assert graph_store.get_node("sys1") is not None

    async def test_merge_missing_node(self, test_app, graph_store):
        await make_node(graph_store, "t1", "资料", "内容")
        resp = test_app.post(
            "/ingest",
            json={"content": "^merge t1 ghost", "event_type": "interaction"},
        )
        assert "不存在" in resp.json()["message"]

    def test_merge_usage_error(self, test_app):
        resp = test_app.post("/ingest", json={"content": "^merge t1", "event_type": "interaction"})
        assert "未执行" in resp.json()["message"]


class TestDeleteCommand:
    async def test_delete_zombie_node(self, test_app, graph_store):
        """无有效源证（僵尸）→ 直接删除。"""
        node = await make_node(graph_store, "z1", "僵尸", "内容", event_id="e1")
        node.source_refs[0].valid = False
        resp = test_app.post("/ingest", json={"content": "^delete z1", "event_type": "interaction"})
        assert "已删除" in resp.json()["message"]
        assert graph_store.get_node("z1") is None

    async def test_delete_protected_refused(self, test_app, graph_store):
        """有有效源证 → 删除保护拒绝。"""
        await make_node(graph_store, "d1", "资料", "内容", event_id="e1")
        resp = test_app.post("/ingest", json={"content": "^delete d1", "event_type": "interaction"})
        msg = resp.json()["message"]
        assert "未执行" in msg and "源证" in msg
        assert graph_store.get_node("d1") is not None

    def test_delete_missing(self, test_app):
        resp = test_app.post(
            "/ingest",
            json={"content": "^delete ghost", "event_type": "interaction"},
        )
        assert "不存在" in resp.json()["message"]

    async def test_delete_system_refused(self, test_app, graph_store):
        """system 节点（手工创建、无事件来源）指令删除拒绝——删除后不可恢复。"""
        await make_node(graph_store, "sys1", "系统", "内容", node_type=NodeType.system)
        resp = test_app.post(
            "/ingest",
            json={"content": "^delete sys1", "event_type": "interaction"},
        )
        msg = resp.json()["message"]
        assert "未执行" in msg and "system" in msg
        assert graph_store.get_node("sys1") is not None


class TestStoreCommand:
    def test_store_creates_event_with_explicit_type(self, test_app):
        before = test_app.get("/events").json()["total"]
        resp = test_app.post(
            "/ingest",
            json={"content": "^data Python 资料正文", "event_type": "interaction"},
        )
        data = resp.json()
        # 存储类创建了真实事件：正常 IngestResponse（command_triggered=False）
        assert data["command_triggered"] is False
        assert data["event_id"]
        assert data["status"] == "indexed"
        assert "已按指令存入" in data["message"]
        ev = test_app.get(f"/events/{data['event_id']}").json()
        assert ev["event_type"] == "data"  # 显式类型，非请求体默认值
        assert ev["raw_content"] == "Python 资料正文"  # 指令前缀不落库
        assert test_app.get("/events").json()["total"] == before + 1

    def test_store_works_without_ai(self, test_app):
        """纯存储不依赖 AI（默认夹具 AI 不可用）。"""
        resp = test_app.post(
            "/ingest",
            json={"content": "^source 原始证据", "event_type": "interaction"},
        )
        data = resp.json()
        assert data["event_id"]
        ev = test_app.get(f"/events/{data['event_id']}").json()
        assert ev["event_type"] == "source"

    def test_store_usage_error(self, test_app):
        resp = test_app.post("/ingest", json={"content": "^data", "event_type": "interaction"})
        assert "未执行" in resp.json()["message"]

    def test_store_pipeline_enqueue(self, test_app, ai_on, monkeypatch):
        """管线启用时存储事件照常入队构图。"""
        monkeypatch.setattr(settings, "agent_mode", "pipeline")
        resp = test_app.post(
            "/ingest",
            json={"content": "^interaction 用户问了X", "event_type": "data"},
        )
        assert resp.json()["event_id"]
        assert len(test_app.enqueued) == 1  # type: ignore[attr-defined]
        assert test_app.enqueued[0].type == "ingest"  # type: ignore[attr-defined]


class TestNodeCommand:
    async def test_create_system_node(self, test_app, graph_store):
        resp = test_app.post(
            "/ingest",
            json={
                "content": "^node system 知识站 | 手工维护的根节点",
                "event_type": "interaction",
            },
        )
        data = resp.json()
        assert data["command_triggered"] is True
        node_id = data["message"].split("：")[1].split("（")[0]
        node = graph_store.get_node(node_id)
        assert node is not None
        assert node.node_type == NodeType.system
        assert node.title == "知识站"
        assert node.content == "手工维护的根节点"
        # FTS 可检索（建节点即建索引）
        r = await graph_store.search_node_fts("知识站")
        assert any(x["node_id"] == node_id for x in r)

    def test_node_usage_error(self, test_app):
        resp = test_app.post(
            "/ingest",
            json={"content": "^node system 只有标题", "event_type": "interaction"},
        )
        assert "未执行" in resp.json()["message"]


class TestHelpCommand:
    def test_help_returns_usage_without_action(self, test_app):
        before = test_app.get("/events").json()["total"]
        resp = test_app.post("/ingest", json={"content": "^help", "event_type": "interaction"})
        data = resp.json()
        assert data["command_triggered"] is True
        assert "支持的指令" in data["message"]
        assert test_app.get("/events").json()["total"] == before  # 未创建事件


class TestBannedFormsStoredAsPlainText:
    """被 ban 的形式（用户定夺）→ 一律普通文本正常落库。"""

    def test_slash_compress_stored_as_text(self, test_app):
        before = test_app.get("/events").json()["total"]
        resp = test_app.post("/ingest", json={"content": "/compress", "event_type": "interaction"})
        data = resp.json()
        assert data["command_triggered"] is False
        assert data["event_id"]
        ev = test_app.get(f"/events/{data['event_id']}").json()
        assert ev["raw_content"] == "/compress"
        assert test_app.get("/events").json()["total"] == before + 1

    def test_chinese_caret_stored_as_text(self, test_app):
        resp = test_app.post("/ingest", json={"content": "^压缩 d1", "event_type": "interaction"})
        assert resp.json()["event_id"]

    def test_colon_form_stored_as_text(self, test_app):
        resp = test_app.post(
            "/ingest",
            json={"content": "^data: 内容", "event_type": "interaction"},
        )
        ev = test_app.get(f"/events/{resp.json()['event_id']}").json()
        assert ev["raw_content"] == "^data: 内容"
        assert ev["event_type"] == "interaction"  # 请求体默认类型


class TestNormalIngestUnaffected:
    def test_normal_content(self, test_app):
        resp = test_app.post("/ingest", json={"content": "普通内容", "event_type": "interaction"})
        data = resp.json()
        assert data["command_triggered"] is False
        assert data["event_id"]
        assert data["status"] == "indexed"


class TestBottomLineDefaults:
    def test_thresholds(self):
        """高水位默认 200：此后每冷却周期都准备压缩。"""
        assert settings.agent_maintain_max_nodes == 200
        assert settings.agent_maintain_cooldown == 60
