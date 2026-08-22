"""asyncio.Queue 消息调度 + Ingest/Query 管线编排"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from controller.task_memory import TaskMemory
from controller.tools import (
    scan_maintenance_candidates,
    tool_analyze_intent,
    tool_apply_maintenance,
    tool_apply_to_store,
    tool_cr_summarize,
    tool_direct_search,
    tool_graph_expand,
    tool_graph_propose,
    tool_graph_query,
    tool_info_split,
    tool_maintain_propose,
    tool_meta_review,
    tool_meta_review_maintenance,
    tool_meta_review_search,
    tool_rrf_merge,
)
from controller.tools._util import issues_text
from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.llm import is_transient_error
from core.models import QueueMessage, SearchRequest, SearchResponse, SearchResult
from core.search import _build_results, retain_relevant_expansion
from core.state import ai_state

logger = logging.getLogger(__name__)


def _cr_prior_text(cr) -> str:
    """将 CrSummary 转为压缩的先验上下文文本，注入 In/Gr 的调用上下文。"""
    lines = [f"- {s}" for s in cr.summary] + [f"#主题: {t}" for t in cr.themes]
    return "\n".join(lines) if lines else ""


class Orchestrator:
    def __init__(self, db: Database, event_store: EventStore, graph_store: GraphStore):
        self.db = db
        self.event_store = event_store
        self.graph_store = graph_store
        self.queue: asyncio.Queue[QueueMessage] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._running = False
        # 补偿退避状态：连续失败批次计数 + 暂停标志（防 LLM 恢复→高负载→再降级震荡）
        self._comp_fail_streak = 0
        self._comp_paused = False
        self._comp_batch_check: asyncio.Task | None = None

    def start(self):
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, msg: QueueMessage):
        await self.queue.put(msg)

    async def _worker_loop(self):
        while self._running:
            try:
                msg = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                await self._dispatch(msg)
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker error processing message")

    async def _dispatch(self, msg: QueueMessage):
        handler = {
            "ingest": self._handle_ingest,
            "delete_event": self._handle_delete_event,
            "delete_node": self._handle_delete_node,
            "modify_node": self._handle_modify_node,
            "modify_edge": self._handle_modify_edge,
            "modify_event_status": self._handle_modify_event_status,
            "compensate": self._handle_compensate,
            "maintain_graph": self._handle_maintain_graph,
        }
        handler_fn = handler.get(msg.type)
        if handler_fn:
            await handler_fn(msg.payload)

    async def _handle_ingest(self, payload: dict[str, Any]) -> None:
        event_id = payload["event_id"]
        event = await self.event_store.get(event_id)
        if event is None:
            return
        # 基础索引：raw → indexed（无 Agent 条件也执行）
        if event["status"] == "raw":
            await self.event_store.insert_fts(event_id, event["raw_content"])
            await self.event_store.update_status(event_id, "indexed")
            event = await self.event_store.get(event_id)
        # source 类型仅存储不构图：停留 indexed，补偿器反复入队也无副作用
        if event["event_type"] == "source":
            logger.info("Event %s indexed (source type, graph skipped)", event_id)
            return
        # 降级 或 未启用 Agent 管线 → 停留 indexed，等待补偿
        if not ai_state.available or settings.agent_mode != "pipeline":
            logger.info("Event %s indexed (agent pipeline inactive)", event_id)
            return
        await self._handle_ingest_pipeline(event_id)

    async def _handle_ingest_pipeline(self, event_id: str) -> None:
        """信息存入管线：In 拆分 → Gr 查询/构图 → Meta 审核 → 写入。

        修正循环：Meta 驳回时把 issues 作为 feedback 注入下一轮 Gr；
        In 的结构性错误（非原文子串）在解析期即失败，直接标记 failed。
        """
        event = await self.event_store.get(event_id)
        if event is None:
            return
        raw = event["raw_content"]
        tm = TaskMemory(task_id=event_id, event_id=event_id, raw_content=raw)
        max_attempts = max(1, settings.agent_max_retries + 1)
        try:
            # 步骤1: Cr 内容要点概括（真实模型，产出辅助上下文）
            cr = await tool_cr_summarize(raw)
            tm.cr_summary = cr
            prior = _cr_prior_text(cr)
            # 并行：In 拆分（基于原文 + Cr 要点）+ Gr 初查（基于 Cr 主题关键词）
            query_text = " ".join(cr.themes) if cr.themes else raw[:500]
            chunks, similar = await asyncio.gather(
                tool_info_split(raw, prior_context=prior),
                tool_graph_query(self.graph_store, query_text),
            )
            tm.annotated_chunks = chunks
            for attempt in range(max_attempts):
                # 第 2+ 轮起基于分块关键词重新查询近似点（截断防超大查询串）
                if attempt > 0:
                    keywords = " ".join(c.content for c in chunks.chunks)[:500]
                    similar = await tool_graph_query(self.graph_store, keywords)
                tm.similar_nodes = similar
                proposal = await tool_graph_propose(
                    chunks, similar, tm.last_feedback, prior_context=prior, event_id=event_id
                )
                tm.graph_proposal = proposal
                verdict = await tool_meta_review(
                    self.graph_store, proposal, raw, chunks, tm.similar_nodes
                )
                tm.meta_verdict = verdict
                if verdict.verdict == "pass":
                    created = await tool_apply_to_store(
                        self.event_store,
                        self.graph_store,
                        proposal,
                        event_id,
                        similar_nodes=tm.similar_nodes,
                    )
                    tm.created_node_ids = created
                    logger.info("Event %s linked with %d nodes", event_id, len(created))
                    # 管线写入后强制落盘，避免防抖阈值内崩溃丢数据（P0-2）
                    await self.graph_store.save()
                    return
                tm.last_feedback = issues_text(verdict.issues)
                tm.attempts += 1
            logger.warning(
                "Event %s agent pipeline failed after %d attempts", event_id, max_attempts
            )
            await self.event_store.update_status(event_id, "failed")
        except Exception as e:
            logger.exception("Agent pipeline error for event %s", event_id)
            if is_transient_error(e):
                # 瞬时错误（超时/断连/5xx）：回到 indexed，等补偿或手动重试，不判死
                logger.warning(
                    "Event %s transient error (%s), back to indexed for retry",
                    event_id, type(e).__name__,
                )
                await self.event_store.update_status(event_id, "indexed")
            else:
                await self.event_store.update_status(event_id, "failed")

    async def run_query(self, request: SearchRequest) -> SearchResponse:
        """Agent 管线检索入口（api.py 在 agent_mode=pipeline 时调用）。"""
        return await self._handle_query_pipeline(request)

    async def _handle_query_pipeline(self, request: SearchRequest) -> SearchResponse:
        """数据检索管线：Cr 意图分析 → 分支检索 → Meta 复核（循环重试）。"""
        if not request.query.strip():
            return SearchResponse(results=[], total=0, degraded=False)
        tm = TaskMemory(task_id="q-" + request.query[:16], query=request.query)
        max_attempts = max(1, settings.agent_max_retries + 1)
        results: list[SearchResult] = []
        paged: list[SearchResult] = []
        total = 0
        for attempt in range(max_attempts):
            intent = await tool_analyze_intent(request.query, tm.last_feedback)
            tm.intent = intent.model_dump()
            if intent.method == "graph_query":
                fts = await tool_direct_search(self.event_store, self.graph_store, request)
                seeds = [
                    r.node_id for r in fts.results if self.graph_store.get_node(r.node_id)
                ]
                expanded = await tool_graph_expand(
                    self.graph_store, seeds, hops=request.max_hops
                )
                # 扩散召回相关性过滤：无向扩散会把与查询无关的邻居混入（搜「游戏」带出「八段锦」）
                expanded = retain_relevant_expansion(
                    self.graph_store, expanded, request.query
                )
                results = await _build_results(expanded, self.event_store, self.graph_store, {})
            else:
                fts = await tool_direct_search(self.event_store, self.graph_store, request)
                c1 = {r.node_id: r.score for r in fts.results}
                if intent.method == "hybrid":
                    seeds = [n for n in c1 if self.graph_store.get_node(n)]
                    c2 = await tool_graph_expand(
                        self.graph_store, seeds, hops=request.max_hops
                    )
                    # 扩散召回相关性过滤（同 graph_query 分支）
                    c2 = retain_relevant_expansion(self.graph_store, c2, request.query)
                    ranked = tool_rrf_merge(c1, c2)
                    results = await _build_results(
                        dict(ranked), self.event_store, self.graph_store, {}
                    )
                else:
                    results = fts.results
            total = len(results)
            sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
            paged = sorted_results[request.offset : request.offset + request.limit]
            verdict = await tool_meta_review_search(
                request.query, sorted_results, tm.intent, tm.last_feedback
            )
            tm.meta_verdict = verdict
            if verdict.verdict == "pass":
                return SearchResponse(results=paged, total=total, degraded=False)
            tm.last_feedback = issues_text(verdict.issues)
            tm.attempts += 1
        return SearchResponse(results=paged, total=total, degraded=False)

    async def _handle_delete_event(self, payload: dict):
        event_id = payload["event_id"]
        result = await self.event_store.delete_with_protection(event_id, self.graph_store)
        if result["status"] == "ok":
            logger.info("Event %s deleted", event_id)
        elif result["status"] == "protected":
            logger.warning("Event %s protected by node %s", event_id, result.get("node_id"))
        elif result["status"] == "not_found":
            logger.warning("Event %s not found", event_id)

    async def _handle_delete_node(self, payload: dict):
        node_id = payload["node_id"]
        force = payload.get("force", False)
        node = self.graph_store.get_node(node_id)
        if node is None:
            return
        valid_refs = [sr for sr in node.source_refs if sr.valid]
        if valid_refs and not force:
            logger.warning("Node %s has %d valid refs, use force", node_id, len(valid_refs))
            return
        self.graph_store.remove_node(node_id)
        await self.graph_store.delete_node_fts(node_id)
        await self.graph_store.flush()
        logger.info("Node %s deleted", node_id)

    async def _handle_modify_node(self, payload: dict):
        node_id = payload["node_id"]
        new_content = payload["new_content"]
        node = self.graph_store.get_node(node_id)
        if node is None:
            return
        # update_node 统一标记脏位：管线内修改同样必须落盘
        updated = self.graph_store.update_node(node_id, content=new_content, confidence=0.7)
        await self.graph_store.upsert_node_fts(node_id, updated.title, updated.content)
        await self.graph_store.flush()

    async def _handle_modify_edge(self, payload: dict):
        from core.models import GraphEdge
        action = payload["action"]
        source = payload["source"]
        target = payload["target"]
        relation = payload["relation"]
        if action == "add":
            evidence_id = payload.get("evidence_event_id", "")
            edge = GraphEdge(
                source=source, target=target,
                relation=relation, evidence_event_id=evidence_id,
            )
            self.graph_store.add_edge(edge)
        elif action == "remove":
            self.graph_store.remove_edge(source, target)
        await self.graph_store.flush()

    async def _handle_modify_event_status(self, payload: dict):
        event_id = payload["event_id"]
        new_status = payload["new_status"]
        await self.event_store.update_status(event_id, new_status)

    async def _handle_maintain_graph(self, payload: dict) -> None:
        """图维护任务：扫描候选 → Gr 维护计划 → Meta 审核 → 执行。

        仅处理「调整/合并/删改」已有图结构；保守优先：
        无候选或计划被 Meta 驳回即放弃本轮，不做修正循环。
        自动触发（AI 恢复，payload.auto=True）受最小图规模约束，手动不受限。
        """
        if not ai_state.available or settings.agent_mode != "pipeline":
            logger.info("Graph maintenance skipped (AI unavailable or pipeline inactive)")
            return
        if (
            payload.get("auto")
            and self.graph_store.total_nodes() < settings.agent_maintain_min_nodes
        ):
            logger.info(
                "Graph maintenance skipped (auto, nodes=%d < min=%d)",
                self.graph_store.total_nodes(),
                settings.agent_maintain_min_nodes,
            )
            return
        candidates = scan_maintenance_candidates(self.graph_store)
        if not any([
            candidates.get("merge_candidates"),
            candidates.get("zombie_nodes"),
            candidates.get("low_conf_isolated"),
            candidates.get("compress_candidates"),
        ]):
            logger.info("Graph maintenance: no candidates")
            return
        try:
            plan = await tool_maintain_propose(self.graph_store, candidates)
            verdict = await tool_meta_review_maintenance(
                self.graph_store, plan, candidates
            )
            if verdict.verdict != "pass":
                logger.warning(
                    "Graph maintenance plan rejected: %s", issues_text(verdict.issues)
                )
                return
            stats = await tool_apply_maintenance(self.event_store, self.graph_store, plan)
            logger.info("Graph maintenance applied: %s", stats)
        except Exception:
            logger.exception("Graph maintenance error")

    async def _handle_compensate(self, payload: dict):
        raw_events = await self.event_store.list_by_status("raw")
        indexed_events = await self.event_store.list_by_status("indexed")
        pending = raw_events + indexed_events
        # 无积压：无论是否暂停，都重置失败计数与暂停状态
        if not pending:
            self._comp_fail_streak = 0
            self._comp_paused = False
            return
        # 连续 2 批失败后暂停自动补偿；force=true（手动触发）打破暂停并重置失败计数
        if self._comp_paused and not payload.get("force"):
            logger.info("Compensation paused (consecutive failures), skip")
            return
        if payload.get("force"):
            self._comp_paused = False
            self._comp_fail_streak = 0
        # 指数退避：连续失败后延迟再试（1,2,4,8…封顶 60s）
        if self._comp_fail_streak > 0:
            delay = min(2 ** (self._comp_fail_streak - 1), 60)
            logger.info("Compensation backoff %ds (fail streak=%d)",
                        delay, self._comp_fail_streak)
            await asyncio.sleep(delay)
        # 首条试探：probe 只处理 1 条，成功后由后续补偿消息继续批量
        probe = bool(payload.get("probe"))
        batch = pending[:1] if probe else pending[: settings.compensate_batch_size]
        logger.info("Compensating %d pending events%s",
                    len(batch), " (probe)" if probe else "")
        for ev in batch:
            msg = QueueMessage(
                type="ingest",
                payload={"event_id": ev["event_id"]},
                timestamp=datetime.now(timezone.utc).timestamp(),
            )
            await self.enqueue(msg)
        if probe:
            self._schedule_batch_check([ev["event_id"] for ev in batch], probe=True)
        else:
            self._schedule_batch_check([ev["event_id"] for ev in batch])

    def _schedule_batch_check(self, event_ids: list[str], probe: bool = False) -> None:
        """延迟检查补偿批次结果：批次事件全部未进入 linked → 视为失败。

        连续 2 批失败 → 暂停自动补偿（手动 force 可恢复）。
        """
        if self._comp_batch_check and not self._comp_batch_check.done():
            return

        async def _check():
            # 批检查延迟独立于健康检查周期（默认 5s）：失败批次快速发现并退避
            await asyncio.sleep(settings.compensate_check_interval)
            if self._comp_paused:
                return
            if probe:
                # 试探批次：成功则继续正常批次，失败则计入失败计数
                if not event_ids:
                    return
                ev = await self.event_store.get(event_ids[0])
                if ev and ev["status"] == "linked":
                    self._comp_fail_streak = 0
                    logger.info("Compensation probe ok, resume batches")
                    # 继续正常批量补偿（不再试探）
                    msg = QueueMessage(
                        type="compensate",
                        payload={},
                        timestamp=datetime.now(timezone.utc).timestamp(),
                    )
                    await self.enqueue(msg)
                else:
                    self._comp_fail_streak += 1
                    logger.warning("Compensation probe failed (streak=%d)",
                                   self._comp_fail_streak)
                return
            done = 0
            for eid in event_ids:
                ev = await self.event_store.get(eid)
                if ev and ev["status"] == "linked":
                    done += 1
            if done > 0:
                self._comp_fail_streak = 0
                logger.info("Compensation batch ok (%d/%d linked)", done, len(event_ids))
            else:
                self._comp_fail_streak += 1
                if self._comp_fail_streak >= 2:
                    self._comp_paused = True
                    logger.warning("Compensation paused after %d failed batches",
                                   self._comp_fail_streak)
                else:
                    logger.warning("Compensation batch failed (streak=%d)",
                                   self._comp_fail_streak)

        self._comp_batch_check = asyncio.create_task(_check())
