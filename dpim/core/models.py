"""Pydantic 数据模型，对应 Spec 所有接口定义"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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


# ── Agent 管线新增模型（《零》方案A）──
# 说明：AnnotatedChunks 替代 InformationFragment 作为信息处理 Agent 的输出。
# 每个分块必须是 raw_content 的原文连续子串（不允许概括/改写），
# 保证元认知可在解析期即完成来源锚定校验。InformationFragment 标记废弃，暂保留兼容。

ChunkType = Literal["interaction", "data", "source", "ignore"]


class SemanticChunk(BaseModel):
    content: str = Field(description="原文连续子串，不可增删改")
    chunk_type: ChunkType = Field(description="分块类型标注")
    label: str = Field(max_length=10, description="10 字以内中文标签")
    confidence: float = Field(ge=0.0, le=1.0, description="分类置信度")


class AnnotatedChunks(BaseModel):
    raw_content: str = Field(description="来源事件原始内容")
    chunks: list[SemanticChunk] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verify_anchor(self) -> "AnnotatedChunks":
        """结构级校验：每个分块必须是 raw_content 的原文连续子串。"""
        for c in self.chunks:
            if c.content and c.content not in self.raw_content:
                raise ValueError(
                    f"chunk '{c.label}' 不是 raw_content 的原文连续子串，禁止改写或概括"
                )
        return self


class QueryIntent(BaseModel):
    method: Literal["direct_search", "graph_query", "hybrid"] = Field(
        description="检索路径选择"
    )
    keywords: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CrSummary(BaseModel):
    """中央控制 Agent 存入概括输出：逐条要点 + 主题方向。

    作为 In 分拣 / Gr 查图的辅助上下文注入，指引切分方向与查图关键词；
    不替代 raw_content（AnnotatedChunks 仍须基于原文子串）。
    """

    summary: list[str] = Field(default_factory=list, description="内容要点逐条概括")
    themes: list[str] = Field(default_factory=list, description="独立主题方向（供图查询关键词）")
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


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
    payload: dict[str, Any]
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


class ModifyEventRequest(BaseModel):
    content: str


class CreateEdgeRequest(BaseModel):
    source: str
    target: str
    relation: str
    evidence_event_id: str = ""


class CreateNodeRequest(BaseModel):
    title: str = Field(max_length=60)
    content: str = ""
    node_type: NodeType = NodeType.data
    source_event_id: str = ""


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
    layers: dict[str, Any]
    last_event_at: str = ""
    version: str = "0.1.0"


# ── dpim-webui 新增模型 ────────────────────

class StateHashResponse(BaseModel):
    hash: str
    changed_at: str


class EventListItem(BaseModel):
    event_id: str
    created_at: str
    raw_content: str
    event_type: str
    status: str


class EventListResponse(BaseModel):
    items: list[EventListItem]
    total: int
    limit: int
    offset: int


class NodeListItem(BaseModel):
    node_id: str
    title: str
    node_type: str
    confidence: float


class NodeListResponse(BaseModel):
    items: list[NodeListItem]
    total: int
    limit: int
    offset: int


class EdgeInfo(BaseModel):
    source: str
    target: str
    relation: str
    evidence_event_id: str


class NodeDetailResponse(BaseModel):
    node_id: str
    title: str
    content: str
    node_type: str
    source_refs: list[dict[str, Any]]
    confidence: float
    metadata: dict[str, Any]
    edges: list[EdgeInfo]


class SettingsResponse(BaseModel):
    memory_db_path: str
    graph_json_path: str
    llm_base_url: str
    llm_api_key: str
    llm_model_name: str
    llm_timeout: int
    available_providers: list[str]
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict,
                                                 description="BYOK 提供商注册表")
    active_provider: str
    available_models: list[str] = Field(default_factory=list)
    active_model: str
    agent_mode: str
    agent_max_retries: int
    agent_cr_model: str
    agent_in_model: str
    agent_gr_model: str
    agent_meta_model: str
    max_graph_hops: int
    rrf_k: int
    jaccard_threshold: float
    health_check_interval: int
    health_check_timeout: int
    compensate_batch_size: int
    log_level: str


class SettingsUpdateRequest(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_name: str | None = None
    llm_timeout: int | None = None
    providers: dict[str, dict[str, Any]] | None = None
    active_provider: str | None = None
    active_model: str | None = None
    agent_mode: str | None = None
    agent_max_retries: int | None = None
    agent_cr_model: str | None = None
    agent_in_model: str | None = None
    agent_gr_model: str | None = None
    agent_meta_model: str | None = None
    max_graph_hops: int | None = None
    rrf_k: int | None = None
    jaccard_threshold: float | None = None
    health_check_interval: int | None = None
    health_check_timeout: int | None = None
    compensate_batch_size: int | None = None
    log_level: str | None = None
