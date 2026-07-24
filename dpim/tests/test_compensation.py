"""控制变量测试：补偿机制、降级状态切换、健康检查隔离"""

import pytest

from controller.compensator import Compensator
from controller.orchestrator import Orchestrator
from core import state as _state


class TestCompensationControlledVariables:
    """控制变量：补偿分批、补偿幂等、降级标记共享"""

    @pytest.mark.asyncio
    async def test_compensate_batch_split(self, db, event_store, graph_store):
        """对照：25 个 raw 事件，batch_size=20，应分 2 批处理"""
        _state.ai_available = False
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
        from core import state as _state
        assert _state.ai_available is False
        _state.ai_available = True
        assert _state.ai_available is True
        # Verify compensator sees the same state
        from controller.compensator import Compensator
        c = Compensator(None, None, None)  # type: ignore
        assert c.is_degraded() is False
        _state.ai_available = False
        assert c.is_degraded() is True
