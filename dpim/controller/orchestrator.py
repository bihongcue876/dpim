"""asyncio.Queue 消息调度 + Ingest 管线编排"""

import asyncio
import logging
from datetime import datetime, timezone

from core.config import settings
from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import QueueMessage

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, db: Database, event_store: EventStore, graph_store: GraphStore):
        self.db = db
        self.event_store = event_store
        self.graph_store = graph_store
        self.queue: asyncio.Queue[QueueMessage] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._running = False

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
        }
        handler_fn = handler.get(msg.type)
        if handler_fn:
            await handler_fn(msg.payload)

    async def _handle_ingest(self, payload: dict):
        event_id = payload["event_id"]
        event = await self.event_store.get(event_id)
        if event is None or event["status"] != "raw":
            return
        # Step: build FTS5 index
        await self.event_store.insert_fts(event_id, event["raw_content"])
        await self.event_store.update_status(event_id, "indexed")
        logger.info("Event %s indexed", event_id)
        # TODO: Agent pipeline (info_processor → graph_builder → metacognition)
        # For now, events stay at indexed until agents are implemented

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
        logger.info("Node %s deleted", node_id)

    async def _handle_modify_node(self, payload: dict):
        node_id = payload["node_id"]
        new_content = payload["new_content"]
        node = self.graph_store.get_node(node_id)
        if node is None:
            return
        node.content = new_content
        node.confidence = 0.7
        self.graph_store.graph.nodes[node_id]["data"] = node
        await self.graph_store.upsert_node_fts(node_id, node.title, node.content)

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

    async def _handle_modify_event_status(self, payload: dict):
        event_id = payload["event_id"]
        new_status = payload["new_status"]
        await self.event_store.update_status(event_id, new_status)

    async def _handle_compensate(self, payload: dict):
        raw_events = await self.event_store.list_by_status("raw")
        indexed_events = await self.event_store.list_by_status("indexed")
        pending = raw_events + indexed_events
        logger.info("Compensating %d pending events", len(pending))
        for i in range(0, len(pending), settings.compensate_batch_size):
            batch = pending[i : i + settings.compensate_batch_size]
            tasks = []
            for ev in batch:
                msg = QueueMessage(
                    type="ingest",
                    payload={"event_id": ev["event_id"]},
                    timestamp=datetime.now(timezone.utc).timestamp(),
                )
                tasks.append(self.enqueue(msg))
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)  # yield
