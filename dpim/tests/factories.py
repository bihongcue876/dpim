"""测试数据工厂：控制变量创建事件、节点、边"""

import hashlib

from core.event_store import EventStore
from core.graph_store import GraphStore
from core.models import GraphEdge, GraphNode, NodeMetadata, NodeType, SourceRef


async def make_event(
    event_store: EventStore,
    content: str,
    event_type: str = "interaction",
    status: str = "indexed",
    graph_refs: list[str] | None = None,
    created_at: str | None = None,
) -> str:
    eid, _ = await event_store.insert(content, event_type)
    # Override created_at if provided
    if created_at:
        await event_store.db.conn.execute(
            "UPDATE events SET created_at = ? WHERE event_id = ?",
            (created_at, eid),
        )
    if status != "raw":
        await event_store.insert_fts(eid, content)
    if graph_refs:
        await event_store.update_status(eid, status, graph_refs=graph_refs)
    elif status != "raw":
        await event_store.update_status(eid, status)
    return eid


async def make_node(
    graph_store: GraphStore,
    node_id: str,
    title: str,
    content: str,
    node_type: NodeType = NodeType.data,
    confidence: float = 0.8,
    event_id: str | None = None,
    evidence_quote: str = "",
) -> GraphNode:
    refs = []
    if event_id:
        h = hashlib.blake2s(content.encode(), digest_size=8).hexdigest()
        refs.append(SourceRef(event_id=event_id, valid=True, hash=h))
    node = GraphNode(
        node_id=node_id,
        title=title,
        content=content,
        node_type=node_type,
        source_refs=refs,
        confidence=confidence,
        metadata=NodeMetadata(evidence_quote=evidence_quote or title),
    )
    graph_store.add_node(node)
    return node


async def make_edge(
    graph_store: GraphStore,
    source: str,
    target: str,
    relation: str = "related_to",
    event_id: str = "evt_dummy",
) -> GraphEdge:
    edge = GraphEdge(
        source=source,
        target=target,
        relation=relation,
        evidence_event_id=event_id,
    )
    graph_store.add_edge(edge)
    return edge
