"""控制变量测试：补偿机制、降级状态切换、健康检查隔离"""

import asyncio

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
        await orchestrator._handle_compensate({"probe": True})
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
        await orchestrator._handle_compensate({})
        assert len(enqueued) == 0  # 暂停中跳过
        await orchestrator._handle_compensate({"force": True})
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
        await orchestrator._handle_compensate({})
        assert sleeps == [1.0]  # 2^(1-1)
        orchestrator._comp_fail_streak = 3
        await orchestrator._handle_compensate({})
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
            await orchestrator._handle_compensate({})
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
        await orchestrator._handle_compensate({})
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
        await orchestrator._handle_compensate({"probe": True})
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
        await orchestrator._handle_compensate({"probe": True})
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
        await orchestrator._handle_compensate({})
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
    async def test_no_pending_resets_state(
        self, db, event_store, graph_store, monkeypatch
    ):
        """对照：无积压事件 → 失败计数与暂停状态清零"""
        ai_state.available = False
        orchestrator = Orchestrator(db, event_store, graph_store)
        orchestrator.enqueue = _null_enqueue
        orchestrator._comp_fail_streak = 3
        orchestrator._comp_paused = True
        await orchestrator._handle_compensate({})
        assert orchestrator._comp_fail_streak == 0
        assert orchestrator._comp_paused is False


async def _null_enqueue(msg):
    """no-op enqueue（测试辅助）"""
    pass
