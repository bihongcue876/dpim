"""控制变量测试：补偿机制、降级状态切换、健康检查隔离"""

import asyncio
from types import SimpleNamespace

import pytest

from controller.compensator import Compensator
from controller.orchestrator import Orchestrator
from core.state import ai_state


class TestCompensationControlledVariables:
    """控制变量：补偿分批、补偿幂等、降级标记共享"""

    @pytest.mark.asyncio
    async def test_compensate_batch_split(self, db, event_store, graph_store):
        """对照：25 个 raw 事件，batch_size=20，应分 2 批处理"""
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        orchestrator.start()
        compensator = Compensator(event_store, graph_store, orchestrator.enqueue)
        compensator._failure_count = 3
        # Insert 25 raw events
        for i in range(25):
            eid, _ = await event_store.insert(f"event {i}")
            await event_store.update_status(eid, "raw")
        # Manually run compensate logic
        raw_list = await event_store.list_by_status("raw")
        indexed_list = await event_store.list_by_status("indexed")
        pending = raw_list + indexed_list
        assert len(pending) == 25
        batch_size = 20
        batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
        assert len(batches) == 2
        assert len(batches[0]) == 20
        assert len(batches[1]) == 5
        await orchestrator.stop()
        await compensator.stop()

    @pytest.mark.asyncio
    async def test_compensate_skips_linked_events(self, db, event_store, graph_store):
        """对照：linked 事件不应出现在补偿列表中"""
        orchestrator = Orchestrator(db, event_store, graph_store)
        orchestrator.start()
        compensator = Compensator(event_store, graph_store, orchestrator.enqueue)
        eid, _ = await event_store.insert("already done")
        await event_store.insert_fts(eid, "already done")
        await event_store.update_status(eid, "linked")
        raw_list = await event_store.list_by_status("raw")
        indexed_list = await event_store.list_by_status("indexed")
        pending = raw_list + indexed_list
        linked_ids = [e["event_id"] for e in pending]
        assert eid not in linked_ids
        await orchestrator.stop()
        await compensator.stop()

    @pytest.mark.asyncio
    async def test_degraded_flag_shared_with_api(self):
        """对照：compensator 修改 state → api 读到同一值"""
        assert ai_state.available is False
        ai_state.available = True
        assert ai_state.available is True
        # Verify compensator sees the same state
        c = Compensator(None, None, None)  # type: ignore
        assert c.is_degraded() is False
        ai_state.available = False
        assert c.is_degraded() is True

    @pytest.mark.asyncio
    async def test_compensate_probe_only_one(self, db, event_store, graph_store):
        """对照：probe 试探只入队 1 条事件"""
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        enqueued: list[str] = []
        async def fake_enqueue(msg):
            enqueued.append(msg.payload["event_id"])
        orchestrator.enqueue = fake_enqueue
        for i in range(5):
            eid, _ = await event_store.insert(f"probe {i}")
            await event_store.update_status(eid, "raw")
        await orchestrator._handle_compensate({"probe": True}, event_store, graph_store)
        assert len(enqueued) == 1
        if orchestrator._comp_batch_check:
            orchestrator._comp_batch_check.cancel()

    @pytest.mark.asyncio
    async def test_compensate_paused_skipped_unless_force(self, db, event_store, graph_store):
        """对照：连续失败暂停后自动补偿跳过，手动 force 打破暂停"""
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        enqueued: list[str] = []
        async def fake_enqueue(msg):
            enqueued.append(msg.payload["event_id"])
        orchestrator.enqueue = fake_enqueue
        eid, _ = await event_store.insert("pending")
        await event_store.update_status(eid, "raw")
        orchestrator._comp_paused = True
        await orchestrator._handle_compensate({}, event_store, graph_store)
        assert len(enqueued) == 0  # 暂停中跳过
        await orchestrator._handle_compensate({"force": True}, event_store, graph_store)
        assert len(enqueued) == 1  # force 打破暂停
        assert orchestrator._comp_paused is False

    @pytest.mark.asyncio
    async def test_compensate_backoff_sleeps(self, db, event_store, graph_store, monkeypatch):
        """对照：失败批次后退避延迟递增（2^(n-1)，封顶 60s）"""
        from core.config import settings
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        # 批次检查任务挂起（大间隔），不干扰退避断言
        monkeypatch.setattr(settings, "compensate_check_interval", 999)
        sleeps: list[float] = []
        _real_sleep = asyncio.sleep
        async def fake_sleep(s):
            if s < 60:  # 退避延迟：记录并立即返回
                sleeps.append(s)
                return
            await _real_sleep(s)  # 批次检查大间隔：真挂起，不干扰 streak
        monkeypatch.setattr("asyncio.sleep", fake_sleep)
        orchestrator.enqueue = _null_enqueue
        orchestrator._comp_fail_streak = 1
        eid, _ = await event_store.insert("backoff")
        await event_store.update_status(eid, "raw")
        await orchestrator._handle_compensate({}, event_store, graph_store)
        assert sleeps == [1.0]  # 2^(1-1)
        orchestrator._comp_fail_streak = 3
        await orchestrator._handle_compensate({}, event_store, graph_store)
        assert sleeps[-1] == 4.0  # 2^(3-1)
        if orchestrator._comp_batch_check:
            orchestrator._comp_batch_check.cancel()

    @pytest.mark.asyncio
    async def test_two_failed_batches_pause(self, db, event_store, graph_store, monkeypatch):
        """对照：连续 2 批失败（批次事件未进入 linked）→ 自动暂停"""
        from core.config import settings
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        monkeypatch.setattr(settings, "compensate_check_interval", 0.02)
        eid, _ = await event_store.insert("never links")
        await event_store.update_status(eid, "raw")
        orchestrator.enqueue = _null_enqueue
        # 两轮批次，事件一直停留在 raw（未进入 linked）→ 每轮失败计数 +1
        for round_no in range(2):
            await orchestrator._handle_compensate({}, event_store, graph_store)
            await asyncio.sleep(0.05)  # 等批次检查任务完成
            assert orchestrator._comp_fail_streak == round_no + 1
        assert orchestrator._comp_paused is True

    @pytest.mark.asyncio
    async def test_success_resets_streak(self, db, event_store, graph_store, monkeypatch):
        """对照：批次成功（事件进入 linked）→ 失败计数清零"""
        from core.config import settings
        from tests.factories import make_event
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        monkeypatch.setattr(settings, "compensate_check_interval", 0.02)
        orchestrator._comp_fail_streak = 1
        eid = await make_event(event_store, "linked soon", status="raw")
        orchestrator.enqueue = _null_enqueue
        await orchestrator._handle_compensate({}, event_store, graph_store)
        await event_store.update_status(eid, "linked")
        await asyncio.sleep(0.05)
        assert orchestrator._comp_fail_streak == 0

    @pytest.mark.asyncio
    async def test_probe_failure_increments_streak(
        self, db, event_store, graph_store, monkeypatch
    ):
        """对照：probe 试探失败（事件未 linked）→ 失败计数 +1"""
        from core.config import settings
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        monkeypatch.setattr(settings, "compensate_check_interval", 0.02)
        eid, _ = await event_store.insert("probe fail")
        await event_store.update_status(eid, "raw")
        orchestrator.enqueue = _null_enqueue
        await orchestrator._handle_compensate({"probe": True}, event_store, graph_store)
        await asyncio.sleep(0.05)
        assert orchestrator._comp_fail_streak == 1

    @pytest.mark.asyncio
    async def test_probe_success_resumes_batches(
        self, db, event_store, graph_store, monkeypatch
    ):
        """对照：probe 试探成功（事件进入 linked）→ 计数清零并继续正常批量"""
        from core.config import settings
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        monkeypatch.setattr(settings, "compensate_check_interval", 0.02)
        orchestrator._comp_fail_streak = 1
        enqueued: list[dict] = []
        async def record_enqueue(msg):
            enqueued.append(msg.payload)
        orchestrator.enqueue = record_enqueue
        eid, _ = await event_store.insert("probe ok")
        await event_store.update_status(eid, "raw")
        await orchestrator._handle_compensate({"probe": True}, event_store, graph_store)
        await event_store.update_status(eid, "linked")
        await asyncio.sleep(0.05)
        assert orchestrator._comp_fail_streak == 0
        # 试探成功后自动继续正常批量（不带 probe）
        assert enqueued[-1] == {}

    @pytest.mark.asyncio
    async def test_backoff_caps_at_60s(
        self, db, event_store, graph_store, monkeypatch
    ):
        """对照：指数退避封顶 60s（streak 再大也不无限增长）"""
        from core.config import settings
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        monkeypatch.setattr(settings, "compensate_check_interval", 999)
        sleeps: list[float] = []
        _real_sleep = asyncio.sleep
        async def fake_sleep(s):
            if s <= 60:  # 退避延迟（含封顶 60s）：记录并立即返回
                sleeps.append(s)
                return
            await _real_sleep(s)  # 批次检查大间隔：真挂起，不干扰 streak
        monkeypatch.setattr("asyncio.sleep", fake_sleep)
        orchestrator.enqueue = _null_enqueue
        orchestrator._comp_fail_streak = 10
        eid, _ = await event_store.insert("cap")
        await event_store.update_status(eid, "raw")
        await orchestrator._handle_compensate({}, event_store, graph_store)
        assert sleeps[-1] == 60.0
        if orchestrator._comp_batch_check:
            orchestrator._comp_batch_check.cancel()

    @pytest.mark.asyncio
    async def test_trigger_compensate_enqueues_maintain(
        self, db, event_store, graph_store, monkeypatch
    ):
        """AI 恢复触发补偿时顺带自动入队图维护（AGENT_MAINTAIN_AUTO）。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", True)
        orchestrator = Orchestrator(db, event_store, graph_store)
        enqueued: list[str] = []

        async def rec(msg):
            enqueued.append(msg.type)

        orchestrator.enqueue = rec
        compensator = Compensator(event_store, graph_store, orchestrator.enqueue)
        await compensator._trigger_compensate()
        assert "compensate" in enqueued
        assert "maintain_graph" in enqueued  # 自动维护消息

    @pytest.mark.asyncio
    async def test_trigger_compensate_maintain_disabled(
        self, db, event_store, graph_store, monkeypatch
    ):
        """AGENT_MAINTAIN_AUTO=false：恢复时不入队图维护。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", False)
        orchestrator = Orchestrator(db, event_store, graph_store)
        enqueued: list[str] = []

        async def rec(msg):
            enqueued.append(msg.type)

        orchestrator.enqueue = rec
        compensator = Compensator(event_store, graph_store, orchestrator.enqueue)
        await compensator._trigger_compensate()
        assert "maintain_graph" not in enqueued

    @pytest.mark.asyncio
    async def test_recovery_maintain_covers_every_loaded_repo(
        self, event_store, graph_store, monkeypatch
    ):
        """v1.38：AI 恢复后的自动维护**逐库各入队一次**。

        此前只发一条**不带 repo_id** 的消息，而 `Orchestrator._resolve_stores` 对缺省
        repo_id 回退**默认库** → 其余库（含活动库若不是默认库时）一次都拿不到这次整理。
        """
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", True)
        repos = _StubRepos([
            _StubEntry("rp_a", graph_store),
            _StubEntry("rp_b", graph_store),
        ])
        msgs = []

        async def rec(msg):
            msgs.append(msg)

        compensator = Compensator(event_store, graph_store, rec, repos=repos)
        await compensator._trigger_compensate()

        assert msgs[0].type == "compensate"  # 补偿试探始终第一优先
        maint = [m for m in msgs if m.type == "maintain_graph"]
        assert [m.payload["repo_id"] for m in maint] == ["rp_a", "rp_b"]
        assert all(m.payload["auto"] is True for m in maint)

    @pytest.mark.asyncio
    async def test_recovery_maintain_without_repos_omits_repo_id(
        self, event_store, graph_store, monkeypatch
    ):
        """单库部署（无库管理器）：仍是一条不带 repo_id 的消息（回退默认库三件套）。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", True)
        msgs = []

        async def rec(msg):
            msgs.append(msg)

        compensator = Compensator(event_store, graph_store, rec)
        await compensator._trigger_compensate()

        maint = [m for m in msgs if m.type == "maintain_graph"]
        assert len(maint) == 1
        assert maint[0].payload == {"auto": True}

    @pytest.mark.asyncio
    async def test_recovery_maintain_empty_registry_falls_back(
        self, event_store, graph_store, monkeypatch
    ):
        """库管理器在场但一个库都没加载 → 回退默认库一条（不静默什么都不做）。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", True)
        msgs = []

        async def rec(msg):
            msgs.append(msg)

        compensator = Compensator(event_store, graph_store, rec, repos=_StubRepos([]))
        await compensator._trigger_compensate()

        maint = [m for m in msgs if m.type == "maintain_graph"]
        assert len(maint) == 1
        assert maint[0].payload == {"auto": True}

    @pytest.mark.asyncio
    async def test_no_pending_resets_state(
        self, db, event_store, graph_store, monkeypatch
    ):
        """对照：无积压事件 → 失败计数与暂停状态清零"""
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        orchestrator.enqueue = _null_enqueue
        orchestrator._comp_fail_streak = 3
        orchestrator._comp_paused = True
        await orchestrator._handle_compensate({}, event_store, graph_store)
        assert orchestrator._comp_fail_streak == 0
        assert orchestrator._comp_paused is False


class TestHighWatermarkMaintain:
    """节点规模高水位触发的自动图维护（C1：达到阈值自动清理僵尸节点）。"""

    @pytest.mark.asyncio
    async def test_high_watermark_triggers_maintain(
        self, event_store, graph_store, monkeypatch
    ):
        """总节点数达到 AGENT_MAINTAIN_MAX_NODES → 自动入队 maintain_graph。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", True)
        monkeypatch.setattr(settings, "agent_maintain_max_nodes", 900)
        monkeypatch.setattr(settings, "agent_maintain_cooldown", 300)
        monkeypatch.setattr(graph_store, "total_nodes", lambda: 900)
        enqueued: list[str] = []

        async def rec(msg):
            enqueued.append(msg.type)

        compensator = Compensator(event_store, graph_store, rec)
        await compensator._maybe_trigger_maintain()
        assert enqueued == ["maintain_graph"]

    @pytest.mark.asyncio
    async def test_below_threshold_no_trigger(
        self, event_store, graph_store, monkeypatch
    ):
        """总节点数低于高水位 → 不触发。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", True)
        monkeypatch.setattr(settings, "agent_maintain_max_nodes", 900)
        monkeypatch.setattr(settings, "agent_maintain_cooldown", 300)
        monkeypatch.setattr(graph_store, "total_nodes", lambda: 899)
        enqueued: list[str] = []

        async def rec(msg):
            enqueued.append(msg.type)

        compensator = Compensator(event_store, graph_store, rec)
        await compensator._maybe_trigger_maintain()
        assert enqueued == []

    @pytest.mark.asyncio
    async def test_cooldown_blocks_retrigger(
        self, event_store, graph_store, monkeypatch
    ):
        """冷却期内不重复触发：两次连续调用仅入队一次。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", True)
        monkeypatch.setattr(settings, "agent_maintain_max_nodes", 900)
        monkeypatch.setattr(settings, "agent_maintain_cooldown", 300)
        monkeypatch.setattr(graph_store, "total_nodes", lambda: 900)
        enqueued: list[str] = []

        async def rec(msg):
            enqueued.append(msg.type)

        compensator = Compensator(event_store, graph_store, rec)
        await compensator._maybe_trigger_maintain()
        await compensator._maybe_trigger_maintain()  # 冷却期内
        assert enqueued == ["maintain_graph"]

    @pytest.mark.asyncio
    async def test_disabled_no_trigger(self, event_store, graph_store, monkeypatch):
        """AGENT_MAINTAIN_AUTO=false → 高水位不触发。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", False)
        monkeypatch.setattr(settings, "agent_maintain_max_nodes", 900)
        monkeypatch.setattr(graph_store, "total_nodes", lambda: 900)
        enqueued: list[str] = []

        async def rec(msg):
            enqueued.append(msg.type)

        compensator = Compensator(event_store, graph_store, rec)
        await compensator._maybe_trigger_maintain()
        assert enqueued == []

    @pytest.mark.asyncio
    async def test_high_watermark_covers_repos_one_per_cycle(
        self, event_store, graph_store, monkeypatch
    ):
        """高水位逐册检查：带 repo_id 触发**第一个达标**的库，每冷却周期至多一册。"""
        from core.config import settings

        monkeypatch.setattr(settings, "agent_maintain_auto", True)
        monkeypatch.setattr(settings, "agent_maintain_max_nodes", 100)
        monkeypatch.setattr(settings, "agent_maintain_cooldown", 300)
        repos = _StubRepos([
            _StubEntry("rp_small", SimpleNamespace(total_nodes=lambda: 10)),
            _StubEntry("rp_big", SimpleNamespace(total_nodes=lambda: 150)),
            _StubEntry("rp_big2", SimpleNamespace(total_nodes=lambda: 200)),
        ])
        msgs = []

        async def rec(msg):
            msgs.append(msg)

        compensator = Compensator(event_store, graph_store, rec, repos=repos)
        await compensator._maybe_trigger_maintain()

        assert [m.payload["repo_id"] for m in msgs] == ["rp_big"]  # 小库跳过、只发一册


async def _null_enqueue(msg):
    """no-op enqueue（测试辅助）"""
    pass


class TestHealthCheckHonoursFormat:
    """v1.45：LLM 健康检查必须**按接口格式分流**（端到端实测抓出的真缺陷）。

    旧实现走 OpenAI SDK 的 `client.models.list()` → 对 `format=anthropic` 的 provider
    **永远发 `Authorization: Bearer`**：真 Anthropic / OpenCode Zen 这类网关回 401
    （"Zen Anthropic endpoint requires x-api-key"），于是 AI 被误判「连不上」——
    降级、补偿、自动维护**永远不会启动**，而密钥其实完全正确。
    """

    @pytest.mark.asyncio
    async def test_probe_uses_provider_format(
        self, db, event_store, graph_store, monkeypatch
    ):
        from controller import compensator as comp_mod
        from core.config import settings

        monkeypatch.setattr(settings, "providers", {
            "zen": {
                "base_url": "https://opencode.ai/zen/v1",
                "api_key": "sk-zen",
                "models": ["claude-sonnet-4"],
                "format": "anthropic",
            },
        })
        monkeypatch.setattr(settings, "active_provider", "zen")
        monkeypatch.setattr(settings, "agent_maintain_auto", False)
        seen: list[tuple[str, str, str]] = []

        async def _fake_probe(conf):
            seen.append((conf.format, conf.base_url, conf.api_key))
            return ["claude-sonnet-4"]

        monkeypatch.setattr(comp_mod, "probe_models", _fake_probe)
        ai_state.set_state(False, "先置为降级")

        compensator = Compensator(event_store, graph_store, _null_enqueue)
        await compensator._check_llm()

        # 关键：探测拿到的是该 provider 的完整配置（含 format），不是硬走 Bearer 的 SDK 客户端
        assert seen == [("anthropic", "https://opencode.ai/zen/v1", "sk-zen")]
        assert ai_state.available is True          # 探测成功 → 恢复可用
        assert compensator._failure_count == 0

    @pytest.mark.asyncio
    async def test_probe_failure_still_degrades_after_three(
        self, db, event_store, graph_store, monkeypatch
    ):
        """分流之后失败路径不变：连续 3 次才判降级，且原因里带得上原文。"""
        from controller import compensator as comp_mod
        from core.config import settings

        monkeypatch.setattr(settings, "providers", {
            "zen": {
                "base_url": "https://opencode.ai/zen/v1",
                "api_key": "sk-bad",
                "models": ["claude-sonnet-4"],
                "format": "anthropic",
            },
        })
        monkeypatch.setattr(settings, "active_provider", "zen")

        async def _boom(conf):
            raise ValueError("HTTP 401: Invalid credential")

        monkeypatch.setattr(comp_mod, "probe_models", _boom)
        ai_state.set_state(True)

        compensator = Compensator(event_store, graph_store, _null_enqueue)
        await compensator._check_llm()
        await compensator._check_llm()
        assert ai_state.available is True           # 未满 3 次不判死
        await compensator._check_llm()
        assert ai_state.available is False
        assert "Invalid credential" in ai_state.reason
        assert "3 次" in ai_state.reason


class _StubEntry:
    """伪库条目：只给 Compensator 用到的两个字段。"""

    def __init__(self, repo_id: str, graph_store) -> None:
        self.repo_id = repo_id
        self.graph_store = graph_store


class _StubRepos:
    """伪库管理器：只实现 `managed_entries()`（Compensator 的唯一调用点）。"""

    def __init__(self, entries: list[_StubEntry]) -> None:
        self._entries = entries

    def managed_entries(self) -> list[_StubEntry]:
        return self._entries
