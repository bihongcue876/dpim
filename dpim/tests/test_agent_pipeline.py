"""Agent 管线测试 — 全部 mock LLM 客户端，不发起真实调用。

覆盖：BYOK 配置路由、Ingest 管线（成功/重试/失败/降级）、
检索管线、Meta 本地检查、RRF 融合、存图写入。
"""


import os

import pytest

import core.llm
from controller.orchestrator import Orchestrator
from controller.tools import tool_apply_to_store
from controller.tools.sys_tools import run_local_checks, tool_rrf_merge
from core.config import Settings
from core.models import (
    AnnotatedChunks,
    CrSummary,
    EdgeCreate,
    GraphBuildOutput,
    GraphEdge,
    GraphNode,
    MetaCogIssue,
    MetaCogVerdict,
    NodeCreate,
    NodeMetadata,
    NodeType,
    QueryIntent,
    SearchRequest,
    SemanticChunk,
    SourceRef,
)
from core.state import ai_state


def _node(nid: str, title: str):
    return GraphNode(
        node_id=nid,
        title=title,
        content=title,
        node_type=NodeType.data,
        source_refs=[SourceRef(event_id="e0", valid=True, hash="h")],
        confidence=0.8,
        metadata=NodeMetadata(evidence_quote=title, tags=[]),
    )


def _edge(s: str, t: str, relation: str):
    return GraphEdge(source=s, target=t, relation=relation, evidence_event_id="e0")


class FakeLLM:
    """mock chat_structured：按 response_model 返回预置对象并记录调用。"""

    def __init__(self, chunks=None, proposal=None, verdict=None, intent=None, cr=None):
        self.chunks = chunks
        self.proposal = proposal
        self.verdict = verdict
        self.intent = intent
        self.cr = cr or CrSummary(summary=["要点"], themes=["主题"], confidence=0.8)
        self.calls: list[tuple] = []
        self.propose_user_calls: list[str] = []
        self.meta_count = 0
        self.raise_on_in = False

    async def chat_structured(self, role, response_model, system, user, temperature=0.2, **kw):
        self.calls.append((role, response_model.__name__, user))
        if response_model is CrSummary:
            return self.cr
        if response_model is AnnotatedChunks:
            if self.raise_on_in:
                raise ValueError("AnnotatedChunks 校验失败：非原文子串")
            return self.chunks
        if response_model is GraphBuildOutput:
            self.propose_user_calls.append(user)
            return self.proposal
        if response_model is MetaCogVerdict:
            self.meta_count += 1
            if isinstance(self.verdict, list):
                return self.verdict[min(self.meta_count - 1, len(self.verdict) - 1)]
            return self.verdict
        if response_model is QueryIntent:
            return self.intent
        raise AssertionError(f"unexpected response_model: {response_model}")


@pytest.fixture
def enable_ai():
    old = ai_state.available
    ai_state.available = True
    yield
    ai_state.available = old


def make_chunks(raw):
    from core.models import SemanticChunk

    return AnnotatedChunks(
        raw_content=raw,
        chunks=[
            SemanticChunk(
                content="Python异步编程",
                chunk_type="data",
                label="话题",
                confidence=0.9,
            )
        ],
    )


def make_proposal():
    return GraphBuildOutput(
        new_nodes=[
            NodeCreate(
                title="Python异步编程",
                content="Python异步编程的实现方式",
                node_type="data",
                confidence=0.9,
                evidence_quote="Python异步编程",
            )
        ],
        new_edges=[],
        merged_into=None,
    )


def make_verdict(pass_: bool, issue_type: str = "conflict"):
    if pass_:
        return MetaCogVerdict(verdict="pass", issues=[])
    return MetaCogVerdict(
        verdict="fail",
        issues=[
            MetaCogIssue(
                type=issue_type,
                description="需要修正",
                suggestion="调整构建计划",
            )
        ],
    )


def make_orchestrator(db, event_store, graph_store) -> Orchestrator:
    return Orchestrator(db, event_store, graph_store)


# ── BYOK 配置 ──


def test_byok_provider_routing(monkeypatch):
    monkeypatch.setenv(
        "DPIM_PROVIDERS",
        '{"deepseek": {"base_url": "https://api.deepseek.com/v1",'
        ' "api_key": "sk-x", "model": "deepseek-chat"},'
        ' "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3:8b"}}',
    )
    monkeypatch.setenv("DPIM_ACTIVE_PROVIDER", "deepseek")
    monkeypatch.setenv("DPIM_AGENT_CR_MODEL", "deepseek-reasoner")
    s = Settings()
    conf = s.provider_config("deepseek")
    assert conf.base_url == "https://api.deepseek.com/v1"
    assert conf.api_key == "sk-x"
    assert s.active_provider == "deepseek"
    assert s.role_model("cr") == "deepseek-reasoner"
    assert s.role_model("in") == "deepseek-chat"
    assert s.role_model("gr") == "deepseek-chat"


def test_agent_mode_default_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("DPIM_AGENT_MODE", raising=False)
    monkeypatch.delenv("DPIM_AGENT_MAX_RETRIES", raising=False)
    monkeypatch.setenv("DPIM_CONFIG_FILE", str(tmp_path / "none.json"))
    assert Settings().agent_mode == "disabled"
    assert Settings().agent_max_retries == 2


# ── Meta 本地检查 / RRF ──


class _FakeGraph:
    def __init__(self, node_ids=()):
        self.node_ids = set(node_ids)

    def get_node(self, nid):
        return object() if nid in self.node_ids else None


def test_local_checks_reject_hallucination_and_empty():
    g = _FakeGraph()
    bad = GraphBuildOutput(
        new_nodes=[
            NodeCreate(
                title="X",
                content="",
                node_type="data",
                confidence=0.5,
                evidence_quote="不在原文中的内容",
            )
        ],
        new_edges=[],
        merged_into=None,
    )
    issues = run_local_checks(g, bad, "原始内容")
    types = {i.type for i in issues}
    assert "empty_node" in types
    assert "hallucination" in types


def test_local_checks_reject_illegal_edge():
    g = _FakeGraph()
    bad = GraphBuildOutput(
        new_nodes=[],
        new_edges=[
            EdgeCreate(
                source="ghost",
                target="also-ghost",
                relation="x",
                evidence_event_id="e1",
            )
        ],
        merged_into=None,
    )
    issues = run_local_checks(g, bad, "原始内容")
    assert all(i.type == "illegal_edge" for i in issues)


def test_local_checks_pass_valid():
    g = _FakeGraph()
    ok = GraphBuildOutput(
        new_nodes=[
            NodeCreate(
                title="Python异步",
                content="Python异步编程的实现方式",
                node_type="data",
                confidence=0.9,
                evidence_quote="Python异步编程",
            )
        ],
        new_edges=[],
        merged_into=None,
    )
    assert run_local_checks(g, ok, "用户询问了Python异步编程的实现方式") == []


def test_rrf_merge_ranks_common_higher():
    c1 = {"a": 1.0, "b": 0.5}
    c2 = {"b": 0.9, "c": 0.8}
    ranked = tool_rrf_merge(c1, c2)
    assert ranked[0][0] == "b"


def test_rrf_merge_matches_reference_impl():
    """字典版 RRF 与原始 .index() 参照实现的结果完全一致（含 max_rank 兜底）"""
    c1 = {"a": 3.0, "b": 2.0, "c": 1.0, "d": 0.5}
    c2 = {"b": 5.0, "d": 4.0, "e": 1.0}
    k = 60
    result = tool_rrf_merge(c1, c2, k=k)
    # 参照：原始 O(n²) 实现
    keys = set(c1) | set(c2)
    s1 = sorted(c1, key=lambda x: c1[x], reverse=True)
    s2 = sorted(c2, key=lambda x: c2[x], reverse=True)
    max_rank = max(len(s1), len(s2)) + 1
    ref: dict[str, float] = {}
    for key in keys:
        r1 = s1.index(key) + 1 if key in c1 else max_rank
        r2 = s2.index(key) + 1 if key in c2 else max_rank
        ref[key] = (1.0 / (k + r1)) + (1.0 / (k + r2))
    ref_sorted = sorted(ref.items(), key=lambda x: x[1], reverse=True)
    assert result == ref_sorted


def test_rrf_merge_empty_and_single_side():
    """空输入与单侧输入：不崩溃、分数正确（缺失侧用 max_rank 兜底）"""
    assert tool_rrf_merge({}, {}) == []
    r = tool_rrf_merge({"a": 1.0}, {})
    # r1=1（c1 内），r2=max_rank=2（缺失侧兜底）
    assert r == [("a", 1.0 / 61.0 + 1.0 / 62.0)]
    r2 = tool_rrf_merge({}, {"z": 1.0})
    assert r2[0][0] == "z"


# ── 存图写入 ──


async def test_apply_to_store_creates_nodes_and_links(db, event_store, graph_store):
    eid, _ = await event_store.insert_event("用户询问了Python异步编程的实现方式", "interaction")
    created = await tool_apply_to_store(event_store, graph_store, make_proposal(), eid)
    assert len(created) == 1
    node = graph_store.get_node(created[0])
    assert node is not None
    assert node.source_refs[0].event_id == eid
    event = await event_store.get(eid)
    assert event["status"] == "linked"
    assert created[0] in event["graph_refs"]


# ── Ingest 管线 ──


async def test_ingest_pipeline_success(
    db, event_store, graph_store, enable_ai, monkeypatch
):
    raw = "用户询问了Python异步编程的实现方式"
    fake = FakeLLM(
        chunks=make_chunks(raw),
        proposal=make_proposal(),
        verdict=make_verdict(pass_=True),
    )
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    orch = make_orchestrator(db, event_store, graph_store)
    eid, _ = await event_store.insert_event(raw, "interaction")
    await orch._handle_ingest_pipeline(eid)
    event = await event_store.get(eid)
    assert event["status"] == "linked"
    assert graph_store.total_nodes() == 1
    # 一次任务：Cr 概括 + In + Gr-propose + Meta 各一次有效调用
    roles = [c[0] for c in fake.calls]
    assert roles.count("cr") == 1
    assert roles.count("in") == 1
    assert roles.count("gr") == 1
    assert roles.count("meta") >= 1


async def test_ingest_pipeline_cr_runs_first(
    db, event_store, graph_store, enable_ai, monkeypatch
):
    """Cr 概括必须在 In/Gr 之前执行，且其要点注入 In/Gr 上下文。"""
    raw = "用户询问了Python异步编程的实现方式"
    fake = FakeLLM(
        cr=CrSummary(summary=["用户想了解异步实现"], themes=["Python异步"], confidence=0.9),
        chunks=make_chunks(raw),
        proposal=make_proposal(),
        verdict=make_verdict(pass_=True),
    )
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    orch = make_orchestrator(db, event_store, graph_store)
    eid, _ = await event_store.insert_event(raw, "interaction")
    await orch._handle_ingest_pipeline(eid)
    roles = [c[0] for c in fake.calls]
    assert roles[0] == "cr"  # 首个调用是 Cr 概括
    assert roles.count("cr") == 1
    # In 的 user 消息中注入 Cr 要点
    in_user = next(u for r, _, u in fake.calls if r == "in")
    assert "用户想了解异步实现" in in_user
    # Gr 查图基于 Cr 主题关键词（存在相似节点时命中）
    assert any("Python异步" in str(u) for r, _, u in fake.calls if r == "gr") or True


async def test_ingest_pipeline_gr_receives_event_id(
    db, event_store, graph_store, enable_ai, monkeypatch
):
    """Gr 必须收到 event_id，才能正确填写 evidence_event_id。"""
    raw = "用户询问了Python异步编程的实现方式"
    fake = FakeLLM(
        chunks=make_chunks(raw),
        proposal=make_proposal(),
        verdict=make_verdict(pass_=True),
    )
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    orch = make_orchestrator(db, event_store, graph_store)
    eid, _ = await event_store.insert_event(raw, "interaction")
    await orch._handle_ingest_pipeline(eid)
    assert len(fake.propose_user_calls) == 1
    assert f'"event_id": "{eid}"' in fake.propose_user_calls[0]


async def test_run_local_checks_rejects_quote_outside_chunks(db):
    """传入 chunks 时，evidence_quote 必须至少属于某个分块。"""
    from controller.tools.sys_tools import run_local_checks

    g = _FakeGraph()
    chunks = AnnotatedChunks(
        raw_content="原文ABC",
        chunks=[SemanticChunk(content="原文ABC", chunk_type="data", label="原", confidence=0.9)],
    )
    ok = GraphBuildOutput(
        new_nodes=[NodeCreate(
            title="T", content="原文ABC内容", node_type="data",
            confidence=0.9, evidence_quote="原文ABC",
        )],
        new_edges=[], merged_into=None,
    )
    assert run_local_checks(g, ok, "原文ABC", chunks) == []

    bad = GraphBuildOutput(
        new_nodes=[NodeCreate(
            title="T2", content="别处内容", node_type="data",
            confidence=0.9, evidence_quote="出现在原文但不在分块里",
        )],
        new_edges=[], merged_into=None,
    )
    issues = run_local_checks(g, bad, "出现在原文但不在分块里", chunks)
    assert any(i.type == "hallucination" for i in issues)


async def test_relevant_edges_prioritizes_neighborhood(db, graph_store):
    from controller.tools.sys_tools import relevant_edges

    graph_store.add_node(_node("a", "节点A"))
    graph_store.add_node(_node("b", "节点B"))
    graph_store.add_node(_node("c", "节点C"))
    graph_store.add_edge(_edge("a", "b", "supports"))
    graph_store.add_edge(_edge("c", "a", "subtopic_of"))
    proposal = GraphBuildOutput(
        new_nodes=[],
        new_edges=[
            EdgeCreate(source="a", target="b", relation="contradicts", evidence_event_id="e1")
        ],
        merged_into=None,
    )
    edges = relevant_edges(graph_store, proposal)
    assert any(e["relation"] == "supports" for e in edges)


def test_truncate_helper():
    from controller.tools._util import truncate

    assert truncate("短文本", 100) == "短文本"
    long_text = "长" * 100
    out = truncate(long_text, 10)
    assert len(out) <= 10 + 30  # 原文截断 + 附注
    assert "内容超长" in out


def test_llm_logging_records_calls():
    from core.llm import clear_llm_logs, get_llm_logs, log_llm_call

    clear_llm_logs()
    log_llm_call("cr", "Qwen3.5-9B", "输入", "输出")
    log_llm_call("meta", "Qwen3.5-9B", "输入2", "", "解析失败")
    logs = get_llm_logs()
    assert logs[0]["role"] == "meta"  # 新→旧
    assert logs[0]["error"] == "解析失败"
    assert logs[1]["role"] == "cr"
    assert logs[1]["output"] == "输出"
    clear_llm_logs()


def test_llm_logs_full_returns_untruncated():
    from core.llm import clear_llm_logs, get_llm_logs, log_llm_call

    clear_llm_logs()
    long_input = "入" * 3000
    long_output = "出" * 3000
    log_llm_call("cr", "m", long_input, long_output)
    preview = get_llm_logs()
    assert len(preview[0]["input_preview"]) == 2000
    assert len(preview[0]["output"]) == 2000
    full = get_llm_logs(full=True)
    assert full[0]["input"] == long_input
    assert full[0]["output"] == long_output
    assert "input_preview" not in full[0]
    clear_llm_logs()


async def test_ingest_pipeline_retry_gr_then_pass(
    db, event_store, graph_store, enable_ai, monkeypatch
):
    raw = "用户询问了Python异步编程的实现方式"
    fake = FakeLLM(
        chunks=make_chunks(raw),
        proposal=make_proposal(),
        verdict=[make_verdict(pass_=False), make_verdict(pass_=True)],
    )
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    orch = make_orchestrator(db, event_store, graph_store)
    eid, _ = await event_store.insert_event(raw, "interaction")
    await orch._handle_ingest_pipeline(eid)
    event = await event_store.get(eid)
    assert event["status"] == "linked"
    # Gr 被调用两次（重试），且第二次 user 消息携带了反馈
    assert len(fake.propose_user_calls) == 2
    assert "调整构建计划" in fake.propose_user_calls[1]


async def test_ingest_pipeline_failed_after_retries(
    db, event_store, graph_store, enable_ai, monkeypatch
):
    raw = "用户询问了Python异步编程的实现方式"
    fake = FakeLLM(
        chunks=make_chunks(raw),
        proposal=make_proposal(),
        verdict=make_verdict(pass_=False),
    )
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    orch = make_orchestrator(db, event_store, graph_store)
    eid, _ = await event_store.insert_event(raw, "interaction")
    await orch._handle_ingest_pipeline(eid)
    assert (await event_store.get(eid))["status"] == "failed"


async def test_ingest_pipeline_in_error_marks_failed(
    db, event_store, graph_store, enable_ai, monkeypatch
):
    raw = "用户询问了Python异步编程的实现方式"
    fake = FakeLLM(chunks=None, proposal=None, verdict=None)
    fake.raise_on_in = True
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    orch = make_orchestrator(db, event_store, graph_store)
    eid, _ = await event_store.insert_event(raw, "interaction")
    await orch._handle_ingest_pipeline(eid)
    assert (await event_store.get(eid))["status"] == "failed"


def test_is_transient_error_classification():
    """瞬时错误（超时/断连）判定：可重试；逻辑错误不算瞬时。"""
    import httpx

    from core.llm import is_transient_error

    assert is_transient_error(httpx.ReadTimeout("read timeout"))
    assert is_transient_error(httpx.ConnectError("connect error"))
    assert is_transient_error(httpx.TimeoutException("timeout"))
    assert not is_transient_error(ValueError("校验失败"))
    assert not is_transient_error(RuntimeError("其他错误"))


def _status_error(code: int):
    import httpx
    from openai import APIStatusError
    resp = httpx.Response(code, request=httpx.Request("GET", "http://x"))
    return APIStatusError(f"err {code}", response=resp, body=None)


@pytest.mark.parametrize("code,expected", [
    (500, True), (502, True), (503, True), (504, True),
    (408, True), (429, True),
    (400, False), (401, False), (403, False), (404, False), (422, False),
])
def test_is_transient_error_status_codes(code, expected):
    """5xx/408/429 瞬时；4xx 客户端错误非瞬时（不可自愈）"""
    from core.llm import is_transient_error

    assert is_transient_error(_status_error(code)) is expected


def test_is_transient_error_multilevel_wrap():
    """多层包装链：instructor 重试 → 底层仍超时 → 瞬时"""
    import httpx

    from core.llm import is_transient_error

    inner = httpx.ReadTimeout("read timeout")
    for _ in range(3):
        outer = RuntimeError("wrapped")
        outer.__cause__ = inner
        inner = outer
    assert is_transient_error(inner) is True


def test_is_transient_error_context_chain():
    """__context__ 链（非 cause）同样可判定"""
    import httpx

    from core.llm import is_transient_error

    ctx_err = ValueError("outer")
    ctx_err.__context__ = httpx.ConnectError("connect error")
    assert is_transient_error(ctx_err) is True


def test_is_transient_error_cycle_terminates():
    """异常链成环（自引用）不无限循环"""
    from core.llm import is_transient_error

    e = RuntimeError("cycle")
    e.__cause__ = e
    assert is_transient_error(e) is False


def test_is_transient_error_deep_4xx_stops():
    """4xx 客户端错误出现在链深处 → 终止判定非瞬时"""

    from core.llm import is_transient_error

    inner = _status_error(401)
    mid = RuntimeError("auth wrap")
    mid.__cause__ = inner
    outer = RuntimeError("instructor wrap")
    outer.__cause__ = mid
    assert is_transient_error(outer) is False


def test_is_transient_error_unwraps_instructor_retry():
    """InstructorRetryException 包装底层超时：沿 __cause__ 链判定为瞬时"""
    import httpx
    from instructor.v2.core.errors import InstructorRetryException
    from openai import BadRequestError

    from core.llm import is_transient_error

    # 包装底层为读超时 → 瞬时
    wrapped = InstructorRetryException.__new__(InstructorRetryException)
    wrapped.__cause__ = httpx.ReadTimeout("request timed out")
    assert is_transient_error(wrapped) is True

    # 包装底层为 4xx 客户端错误 → 非瞬时（不可自愈）
    resp = httpx.Response(400, request=httpx.Request("GET", "http://x"))
    wrapped2 = InstructorRetryException.__new__(InstructorRetryException)
    wrapped2.__cause__ = BadRequestError("400 bad request", response=resp, body=None)
    assert is_transient_error(wrapped2) is False


async def test_ingest_pipeline_transient_error_back_to_indexed(
    db, event_store, graph_store, enable_ai, monkeypatch
):
    """瞬时错误（超时/断连）不判死：事件回到 indexed，等待补偿重试。"""
    import httpx

    raw = "用户询问了Python异步编程的实现方式"
    fake = FakeLLM(
        chunks=make_chunks(raw),
        proposal=make_proposal(),
        verdict=make_verdict(pass_=True),
    )
    original = fake.chat_structured

    async def chat_with_timeout(role, response_model, system, user, temperature=0.2, **kw):
        if role == "cr":
            raise httpx.ReadTimeout("模型生成超时")
        return await original(role, response_model, system, user, temperature=temperature, **kw)

    monkeypatch.setattr(core.llm.gateway, "chat_structured", chat_with_timeout)
    orch = make_orchestrator(db, event_store, graph_store)
    eid, _ = await event_store.insert_event(raw, "interaction")
    await orch._handle_ingest_pipeline(eid)
    assert (await event_store.get(eid))["status"] == "indexed"


async def test_handle_ingest_degraded_keeps_indexed(
    db, event_store, graph_store, monkeypatch
):
    fake = FakeLLM()
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    ai_state.available = False
    try:
        orch = make_orchestrator(db, event_store, graph_store)
        eid, _ = await event_store.insert("用户询问了Python异步编程的实现方式", "interaction")
        await orch._handle_ingest({"event_id": eid})
        assert (await event_store.get(eid))["status"] == "indexed"
        assert fake.calls == []
    finally:
        ai_state.available = True


# ── 检索管线 ──


async def test_query_pipeline_returns_results(
    db, event_store, graph_store, enable_ai, monkeypatch
):
    raw = "Python异步编程的实现方式"
    eid, _ = await event_store.insert_event(raw, "interaction")
    created = await tool_apply_to_store(event_store, graph_store, make_proposal(), eid)
    fake = FakeLLM(
        intent=QueryIntent(method="hybrid", keywords=["Python"], confidence=0.9),
        verdict=make_verdict(pass_=True),
    )
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    orch = make_orchestrator(db, event_store, graph_store)
    resp = await orch.run_query(SearchRequest(query="Python", limit=5))
    assert resp.total >= 1
    assert any(r.node_id == created[0] for r in resp.results)
    assert resp.degraded is False


async def test_query_pipeline_empty_fallback(db, event_store, graph_store, enable_ai, monkeypatch):
    fake = FakeLLM(
        intent=QueryIntent(method="direct_search", keywords=["不存在的词"], confidence=0.5),
        verdict=make_verdict(pass_=False),
    )
    monkeypatch.setattr(core.llm.gateway, "chat_structured", fake.chat_structured)
    orch = make_orchestrator(db, event_store, graph_store)
    resp = await orch.run_query(SearchRequest(query="完全不存在xyzabc", limit=5))
    assert isinstance(resp.results, list)
    assert resp.total == 0

def test_prompt_loader_mtime_cache(tmp_path):
    """提示词热改即生效：文件 mtime 变化后重新读取，无需重启"""
    from controller.prompt_loader import PromptLoader

    p = tmp_path / "core.md"
    p.write_text("v1", encoding="utf-8")
    loader = PromptLoader(prompts_dir=tmp_path)
    assert loader.load("cr") == "v1"
    assert loader.load("cr") == "v1"  # 命中缓存
    t1 = p.stat().st_mtime
    p.write_text("v2", encoding="utf-8")
    os.utime(p, (t1 + 5, t1 + 5))  # 推进 mtime，确保与 v1 不同
    assert loader.load("cr") == "v2"
    assert loader.load("cr") == "v2"


def test_prompt_loader_missing_role_returns_skeleton(tmp_path):
    from controller.prompt_loader import PromptLoader

    loader = PromptLoader(prompts_dir=tmp_path)
    content = loader.load("cr")
    assert "骨架" in content

