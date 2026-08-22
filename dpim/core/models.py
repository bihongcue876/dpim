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


# ── 图维护（图结构调整/合并/删改/节点压缩，2026-08-18 新增）──
# 说明：维护计划由 Gr 产出、Meta 审核、tool_apply_maintenance 执行。
# 边界（与协议删除保护对齐）：system 节点永不参与；data 仅无有效源证可删；
# 合并仅同类型；修改仅 interaction（data 只追加）；压缩仅 data（概括/精炼标题/补边）；
# 保守优先，空计划合法。


class MaintenanceMerge(BaseModel):
    """合并多个已有节点进 target（target 吸收源证/内容/边后删除 source）。"""

    target_id: str
    source_ids: list[str] = []
    reason: str = ""


class MaintenanceDelete(BaseModel):
    node_id: str
    reason: str = ""


class MaintenanceUpdate(BaseModel):
    """调整节点内容：interaction 覆盖式；data 由执行层转为追加行。"""

    node_id: str
    content: str
    reason: str = ""


class MaintenanceEdgeRemove(BaseModel):
    source: str
    target: str
    relation: str = ""
    reason: str = ""


class MaintenanceEdgeAdd(BaseModel):
    """压缩时补充的关系：把概括后可能丢失的隐含关系显式化为边。"""

    source: str
    target: str
    relation: str
    reason: str = ""


class MaintenanceCompress(BaseModel):
    """压缩 data 节点：概括 content + 精炼 title + 补充关系（边），保留源证与语义。

    与 updates 的区别：updates 对 data 只追加、对 interaction 覆盖；
    compresses 是对 data 的概括压缩（覆盖 content、可优化 title、可补边），
    是「节点压缩」的专门通道。system / interaction 不参与。
    """

    node_id: str
    content: str
    title: str = ""
    new_edges: list[MaintenanceEdgeAdd] = []
    reason: str = ""


class GraphMaintenancePlan(BaseModel):
    merges: list[MaintenanceMerge] = []
    deletes: list[MaintenanceDelete] = []
    updates: list[MaintenanceUpdate] = []
    edge_removes: list[MaintenanceEdgeRemove] = []
    compresses: list[MaintenanceCompress] = []
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


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
    # 内容上限：防无限写入撑爆 SQLite/FTS5（磁盘耗尽 DoS）
    content: str = Field(max_length=1_000_000)
    # 必填枚举：auto 模式已移除（历史上 auto 仅静默落库为 interaction，无 AI 分类）
    event_type: EventType


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
    # 与 IngestRequest.content 同上限：修订路径同样防磁盘耗尽
    content: str = Field(max_length=1_000_000)
    # 可选类型修订：None = 保持不变。仅改线层事件类型，
    # 不联动已生成图节点（图层为派生物，节点层走图维护或删除重建）
    event_type: EventType | None = None


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
    # 服务端范围约束（前端只约束 UI，直连 API 需 Pydantic 拦截）：
    # max_hops 防全图遍历（0 = 不扩散，事件原文/知识节点纯检索用；1-5 = 扩散跳数），
    # limit/offset 防超大分页拖垮内存
    max_hops: int = Field(default=2, ge=0, le=5)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


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
    version: str = "0.2.1"


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
    llm_max_tokens: int | None = None
    llm_enable_thinking: bool | None = None
    llm_thinking_budget: int | None = None
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
    """PUT /settings 请求体 — 字段白名单 + 值域约束（与前端输入范围对齐）。

    安全语义：
    - 枚举字段（agent_mode / log_level）非法值直接 422，杜绝任意字符串注入运行时
    - llm_api_key / providers[*].api_key 支持掩码幂等：提交掩码或空 = 保留现值
      （掩码格式 `xxx****xxxx`，见 core/security.py）
    """
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_name: str | None = None
    # 存储路径（v1.16）：可经前端修改，持久化 dpim.json，重启生效（数据文件不自动迁移）
    memory_db_path: str | None = None
    graph_json_path: str | None = None
    llm_timeout: int | None = Field(default=None, ge=1, le=3600)
    llm_max_tokens: int | None = Field(default=None, ge=0, le=32768)
    llm_enable_thinking: bool | None = None
    llm_thinking_budget: int | None = Field(default=None, ge=0, le=32768)
    providers: dict[str, dict[str, Any]] | None = None
    active_provider: str | None = None
    active_model: str | None = None
    agent_mode: Literal["disabled", "pipeline"] | None = None
    agent_max_retries: int | None = Field(default=None, ge=0, le=10)
    agent_cr_model: str | None = None
    agent_in_model: str | None = None
    agent_gr_model: str | None = None
    agent_meta_model: str | None = None
    max_graph_hops: int | None = Field(default=None, ge=1, le=5)
    rrf_k: int | None = Field(default=None, ge=1, le=200)
    jaccard_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    health_check_interval: int | None = Field(default=None, ge=10, le=86400)
    health_check_timeout: int | None = Field(default=None, ge=10, le=3600)
    compensate_batch_size: int | None = Field(default=None, ge=5, le=100)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None
