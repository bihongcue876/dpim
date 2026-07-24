"""Pydantic 数据模型，对应 Spec 所有接口定义"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    interaction = "interaction"
    data = "data"
    source = "source"


class EventStatus(str, Enum):
    raw = "raw"
    indexed = "indexed"
    linked = "linked"
    failed = "failed"
    skipped = "skipped"


class NodeType(str, Enum):
    system = "system"
    interaction = "interaction"
    data = "data"


class SourceRef(BaseModel):
    event_id: str
    valid: bool
    hash: str


class NodeMetadata(BaseModel):
    evidence_quote: str
    tags: list[str] = []
    protected: bool = False
    conflict: bool = False


class GraphNode(BaseModel):
    node_id: str
    title: str = Field(max_length=60)
    content: str
    node_type: NodeType
    source_refs: list[SourceRef]
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: NodeMetadata


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    evidence_event_id: str
    note: str = ""


class Event(BaseModel):
    event_id: str
    created_at: str
    raw_content: str
    content_hash: str
    event_type: EventType
    status: EventStatus = EventStatus.raw
    graph_refs: list[str] = []


class InformationFragment(BaseModel):
    interaction: list[str] = []
    data: list[str] = []
    source: str = ""


class NodeCreate(BaseModel):
    title: str
    content: str
    node_type: NodeType
    confidence: float
    evidence_quote: str


class EdgeCreate(BaseModel):
    source: str
    target: str
    relation: str
    evidence_event_id: str


class GraphBuildOutput(BaseModel):
    new_nodes: list[NodeCreate] = []
    new_edges: list[EdgeCreate] = []
    merged_into: str | None = None


class MetaCogIssue(BaseModel):
    type: str
    description: str
    suggestion: str


class MetaCogVerdict(BaseModel):
    verdict: str
    issues: list[MetaCogIssue] = []


class QueueMessage(BaseModel):
    type: str
    payload: dict
    timestamp: float


class IngestRequest(BaseModel):
    content: str
    event_type: str = "auto"


class IngestResponse(BaseModel):
    event_id: str
    status: EventStatus
    message: str


class DeleteNodeRequest(BaseModel):
    force: bool = False


class ModifyNodeRequest(BaseModel):
    content: str


class ModifyEventStatusRequest(BaseModel):
    status: EventStatus


class SearchRequest(BaseModel):
    query: str
    source_filter: str = "all"
    max_hops: int = 2
    limit: int = 20
    offset: int = 0


class SearchResult(BaseModel):
    node_id: str
    title: str
    snippet: str
    score: float
    source_events: list[str]
    source_type: str
    confidence: float
    degraded: bool


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    degraded: bool


class FeedbackRequest(BaseModel):
    result_id: str
    accepted: bool


class HealthResponse(BaseModel):
    status: str
    ai_available: bool
    layers: dict
    last_event_at: str = ""
    version: str = "0.1.0"
