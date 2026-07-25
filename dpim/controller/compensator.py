"""降级检测 + LLM 健康检查 + 自动补偿"""

import asyncio
import logging

from core.config import settings
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.llm import create_client
from core.models import QueueMessage
from core.state import ai_state, refresh_key

logger = logging.getLogger(__name__)


class Compensator:
    def __init__(self, event_store: EventStore, graph_store: GraphStore, enqueue_fn):
        self.event_store = event_store
        self.graph_store = graph_store
        self.enqueue = enqueue_fn
        self._failure_count = 0
        self._health_task: asyncio.Task | None = None
        self._running = False
        self._client = create_client()

    def start(self):
        self._running = True
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop(self):
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

    async def _health_loop(self):
        await asyncio.sleep(5)  # initial delay
        while self._running:
            try:
                await self._check_llm()
            except Exception:
                logger.exception("Health check error")
            await asyncio.sleep(settings.health_check_interval)

    async def _check_llm(self):
        try:
            await asyncio.wait_for(
                self._client.models.list(),
                timeout=settings.llm_timeout,
            )
            self._failure_count = 0
            if not ai_state.available:
                ai_state.available = True
                refresh_key()
                logger.info("LLM recovered, starting compensation")
                await self._trigger_compensate()
        except Exception:
            self._failure_count += 1
            logger.warning("LLM health check failed (%d/3)", self._failure_count)
            if self._failure_count >= 3:
                ai_state.available = False
                refresh_key()

    def is_degraded(self) -> bool:
        return not ai_state.available

    async def _trigger_compensate(self):
        msg = QueueMessage(
            type="compensate",
            payload={},
            timestamp=__import__("time").time(),
        )
        await self.enqueue(msg)
