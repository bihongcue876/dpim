"""降级检测 + LLM 健康检查 + 自动补偿"""

import asyncio
import logging
import time

from core.config import settings
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.llm import create_client
from core.models import QueueMessage
from core.state import ai_state, refresh_key

logger = logging.getLogger(__name__)


class Compensator:
    def __init__(self, event_store: EventStore, graph_store: GraphStore, enqueue_fn, repos=None):
        self.event_store = event_store
        self.graph_store = graph_store
        self.enqueue = enqueue_fn
        # 库管理器（可选）：提供时高水位维护逐受管库检查（默认库优先）
        self.repos = repos
        self._failure_count = 0
        self._health_task: asyncio.Task | None = None
        self._running = False
        # 节点规模高水位触发的自动维护：记录上次触发时刻，冷却期内不重复触发
        self._last_auto_maintain = 0.0
        # 健康检查互斥锁：前端 PUT /settings 与后台健康循环并发触发时串行执行，
        # 避免 _failure_count 计数串扰导致状态翻转不一致
        self._check_lock = asyncio.Lock()
        # 注意：不缓存客户端 —— 前端 PUT /settings 切换 provider 后，
        # 健康检查立即跟随新 provider（gateway.client 内部按 base_url/api_key 缓存，动态取零开销）

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
                await self._maybe_trigger_maintain()
            except Exception:
                logger.exception("Health check error")
            await asyncio.sleep(settings.health_check_interval)

    async def _check_llm(self) -> None:
        async with self._check_lock:
            try:
                # 每次动态取客户端：跟随当前活动 provider（前端切配置立即生效）
                client = create_client()
                # 健康检查用独立超时（health_check_timeout），与生成超时分离：
                # 模型加载/单槽忙碌时不至于快速 3 连败假降级
                await asyncio.wait_for(
                    client.models.list(),
                    timeout=settings.health_check_timeout,
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
        # 首条试探模式：AI 恢复后先只处理 1 条事件验证稳定性，
        # 试探成功由 orchestrator 自动继续批量，失败则退避（防雪崩震荡）
        msg = QueueMessage(
            type="compensate",
            payload={"probe": True},
            timestamp=__import__("time").time(),
        )
        await self.enqueue(msg)
        # 自动图维护：AI 恢复后顺带整理图谱（合并冗余/清理僵尸/修正内容）；
        # 扫描无候选即跳过；小图由 AGENT_MAINTAIN_MIN_NODES 拦截（orchestrator 侧）
        if settings.agent_maintain_auto:
            maint = QueueMessage(
                type="maintain_graph",
                payload={"auto": True},
                timestamp=__import__("time").time(),
            )
            await self.enqueue(maint)

    async def _maybe_trigger_maintain(self) -> None:
        """节点规模高水位触发的自动图维护（与 AI 恢复触发互补）。

        受管库逐册检查（v1.29，默认库优先）：任一册节点数达到
        AGENT_MAINTAIN_MAX_NODES 即入队一次该册的图维护；独立于 AI 恢复，
        健康检查循环周期调用。冷却期内不重复触发，避免每周期空转 LLM。
        """
        if not settings.agent_maintain_auto:
            return
        now = time.time()
        if now - self._last_auto_maintain < settings.agent_maintain_cooldown:
            return
        # 逐受管库检查（无库管理器时仅默认库）
        if self.repos is not None:
            candidates = [
                (entry.repo_id, entry.graph_store) for entry in self.repos.managed_entries()
            ]
        else:
            candidates = [("", self.graph_store)]
        for repo_id, graph_store in candidates:
            total = graph_store.total_nodes()
            if total < settings.agent_maintain_max_nodes:
                continue
            self._last_auto_maintain = now
            payload = {"auto": True}
            if repo_id:
                payload["repo_id"] = repo_id
            await self.enqueue(
                QueueMessage(type="maintain_graph", payload=payload, timestamp=now)
            )
            logger.info(
                "Auto-maintain triggered (repo=%s, nodes=%d >= %d)",
                repo_id or "default", total, settings.agent_maintain_max_nodes,
            )
            return  # 每个冷却周期至多触发一册，防积压期雪崩
