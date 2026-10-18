"""Pydantic 数据模型，对应 Spec 所有接口定义"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from core.config import settings


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


# ── Agent 管线新增模型（《零》方案A）──
# 说明：AnnotatedChunks 是信息处理 Agent 的输出（v1.30 起 InformationFragment 已删除）。
# 每个分块必须是 raw_content 的原文连续子串（不允许概括/改写），
# 保证元认知可在解析期即完成来源锚定校验。

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


class MaintenanceNodeAdd(BaseModel):
    """update 模式补缺失要点（v1.24）：把事件中提到但图中缺失的关键点补成节点。

    证据锚定：event_id 必须是已有事件，evidence_quote 必须是该事件原文的
    连续子串（本地硬校验，杜绝幻觉）；可选 parent_node_id 挂为子节点
    （subtopic_of 边）。system 类型不允许。
    """

    title: str = Field(max_length=60)
    content: str
    node_type: NodeType = NodeType.data
    event_id: str
    evidence_quote: str
    parent_node_id: str = ""
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
    edge_adds: list[MaintenanceEdgeAdd] = []
    node_adds: list[MaintenanceNodeAdd] = []
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


class MaintainRequest(BaseModel):
    """手动图维护请求（v1.32）：`mode` 决定维护口径。

    - `update`（默认）：两阶段结构优化——Phase1 减碎+补缺（含 node_adds）→ Phase2 连线；
    - `compress`：删繁就简（压缩 data 节点 / 合并 / 删僵尸）。

    此前 REST 端点**完全不读 body**，payload 恒为 `{}` → orchestrator 的
    `payload.get("mode")` 永远为 None →「前端选 update 实际走 compress」，
    `^update` 的两阶段能力只有 `^指令` 一条路可达。
    """

    mode: Literal["compress", "update"] = "update"


class IngestRequest(BaseModel):
    # 内容上限：防无限写入撑爆 SQLite/FTS5（磁盘耗尽 DoS）
    content: str = Field(max_length=1_000_000)
    # 必填枚举：auto 模式已移除（历史上 auto 仅静默落库为 interaction，无 AI 分类）
    event_type: EventType
    # 目标册（v1.29）：空 = 活动库
    repo_id: str = ""


class IngestResponse(BaseModel):
    event_id: str
    status: EventStatus
    message: str
    # 对话指令触发（/压缩、/合并、/delete、/data: 等）：未创建事件时
    # event_id 为空、status=skipped；message 携带面向用户的执行结果
    command_triggered: bool = False


class DeleteNodeRequest(BaseModel):
    force: bool = False


class ModifyNodeRequest(BaseModel):
    """节点修改：内容修改与源事件增删可任选（至少一项）。

    - content：修改内容（system 节点禁止）
    - add_source_event_id：追加源事件（幂等，事件须存在）
    - remove_source_event_id：移除源事件（移除后须仍保留 ≥1 条有效源证）
    """

    content: str = ""
    add_source_event_id: str = ""
    remove_source_event_id: str = ""


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
    # v1.36：不传时取「运行配置 → 图谱最大跳数」（`settings.max_graph_hops`）——
    # 此前这里是写死的 2，于是界面上那个字段**任何代码都没读**（配了等于没配）。
    max_hops: int = Field(default_factory=lambda: settings.max_graph_hops, ge=0, le=5)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    # 册范围（v1.29 联合检索）：None = 全部受管库；["bk_x"] = 单册；多值 = 限定联合
    repo_ids: list[str] | None = None


class SearchResult(BaseModel):
    node_id: str
    title: str
    snippet: str
    score: float
    source_events: list[str]
    source_type: str
    confidence: float
    degraded: bool
    # 结果种类（v1.29）：node = 图节点，event = 事件原文（联合检索去重键依赖）
    kind: str = "node"
    # 来源册锚定（v1.29）：单册检索填所属册；联合检索被去重合并时
    # repo_id/repo_name 为首命中册，source_repos 列出全部来源库名
    repo_id: str = ""
    repo_name: str = ""
    source_repos: list[str] = []
    # 事件内容哈希（v1.29，仅 kind=event）：联合检索跨册去重键
    content_hash: str = ""


class JointHitTrace(BaseModel):
    """联合检索单条结果的融合轨迹：它在各库的排名 / 原始分 / RRF 增益。"""

    node_id: str
    title: str = ""
    kind: str = "node"
    repo_id: str = ""
    repo_name: str = ""
    source_repos: list[str] = []
    contributions: list[dict[str, Any]] = []


class JointRepoTrace(BaseModel):
    """联合检索中单库的参与情况。"""

    repo_id: str
    repo_name: str
    candidates: int = 0
    elapsed_ms: int = 0


class JointTrace(BaseModel):
    """联合检索融合轨迹（v1.30）：候选池大小 / 去重统计 / 每库参与 / 每条结果明细。"""

    candidate_pool: int = 0
    merged_total: int = 0
    deduped: int = 0
    elapsed_ms: int = 0
    per_repo: list[JointRepoTrace] = []
    # 只包含本页结果（避免轨迹随全量结果膨胀）
    hits: list[JointHitTrace] = []


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    degraded: bool
    # 联合检索融合轨迹（v1.30；单库检索为 None）
    trace: JointTrace | None = None


class FeedbackRequest(BaseModel):
    result_id: str
    accepted: bool
    # 库作用域（v1.30）：缺省 = 活动库；跨库跳转来的结果必须带上，否则反馈静默落在活动库
    repo_id: str = ""


class HealthResponse(BaseModel):
    """`/health` 响应。

    v1.34：`status` 增第三态 `unconfigured`（**没配 AI**，与 `degraded`「配了但连不上」
    严格区分）；`ai_unavailable_reason` 给出可直接展示的中文原因。
    """
    status: str  # ok | degraded | unconfigured
    ai_available: bool
    ai_unavailable_reason: str = ""
    layers: dict[str, Any]
    last_event_at: str = ""
    version: str = "0.4.0"
    # 队列与册可见性（v1.29）：队列积压深度 / worker 运行态 / 活动库 id
    queue_depth: int = 0
    worker_running: bool = False
    active_repo_id: str = ""
    # 存储容量与备份（P4）：db/wal/json 体积、备份份数、图层操作日志条数
    storage: dict[str, Any] = {}


# ── 册（Repo）模型（v1.29：一库 = 一 memory.db + 一 graph.json） ────────────────────


class RepoCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)
    # 书库展示名（可选分组；路径用独立生成的 group_key，展示名不入路径）
    group: str = Field(default="", max_length=60)
    root_kind: Literal["managed", "external"] = "managed"
    # external 必填：已存在目录（须含 memory.db + graph.json），只登记不复制
    root: str = Field(default="", max_length=1024)


class RepoAdoptRequest(BaseModel):
    """收养既有目录（v1.32）：目录里**至少有一个**库文件，缺的那个按需补空件。

    external 登记（`RepoCreateRequest(root_kind="external")`）要求两文件齐备，
    半损状态（graph.json 被误删 / 只有一份 memory.db 要接管）走不通；收养补的就是这个口子。
    """

    root: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)
    group: str = Field(default="", max_length=60)
    # True = 缺哪个补哪个（**只补空件**，绝不覆盖已存在的文件）；
    # False = 缺件即拒绝（用户想先自己查清楚）
    adopt_missing: bool = True


class RepoUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)
    group: str | None = Field(default=None, max_length=60)
    # 受管开关（v1.29）：false = 休眠（不加载不检索不构图）；切换即时生效
    managed: bool | None = None
    # 外部库重指向（v1.31）：换目录 = 重新登记 db/json 路径（须含两文件，禁设清单校验）；
    # 受管库目录由系统管理，传 root 直接 400
    root: str | None = Field(default=None, max_length=1024)


class RepoInfo(BaseModel):
    repo_id: str
    name: str
    note: str = ""
    group: str | None = None
    root_kind: str = "external"
    managed: bool = True
    active: bool = False
    loaded: bool = False
    # 未加载原因（v1.32，P6 失败可见）：加载失败原因优先；否则给出可下手的现状原因
    # （休眠 / 库目录不存在 / 登记文件缺失）；已加载为空串
    load_error: str = ""
    # 计数仅受管且已加载的册给出；休眠库为 None（不打开文件）
    total_events: int | None = None
    total_nodes: int | None = None
    db_path: str = ""
    json_path: str = ""
    created_at: str = ""
    updated_at: str = ""


class RepoListResponse(BaseModel):
    repos: list[RepoInfo]
    active_repo_id: str


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
    # 失败原因（v1.28 T0-4）：脱敏错误摘要，仅 failed 事件非空
    error: str = ""
    # 来源库归属（v1.31）：联合列表必须知道每行来自哪个库；
    # 单库查询填该库 id/name；库登记未初始化（回落路径）时为空串
    repo_id: str = ""
    repo_name: str = ""


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
    # 来源库归属（v1.31）：同 EventListItem.repo_id/repo_name
    repo_id: str = ""
    repo_name: str = ""


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


class EdgeListItem(BaseModel):
    """边列表项（GET /edges，v1.37）：EdgeInfo + 来源库归属（联合列表用）。"""
    source: str
    target: str
    relation: str
    evidence_event_id: str
    # 来源库归属（v1.37）：同 NodeListItem.repo_id/repo_name
    repo_id: str = ""
    repo_name: str = ""


class EdgeListResponse(BaseModel):
    items: list[EdgeListItem]
    total: int
    limit: int
    offset: int


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
    """GET /settings 响应。

    v1.34：**AI 身份只在 `providers` 里**——不再下发 `llm_base_url` / `llm_api_key` /
    `llm_model_name` / `llm_timeout` / `llm_max_tokens` / `llm_enable_thinking` /
    `llm_thinking_budget`（那套「主配置」已删除，与 provider 条目重复且会互相打架）。
    未配置状态由 `llm_configured` + `llm_unavailable_reason` 如实给出。
    """
    memory_db_path: str
    graph_json_path: str
    available_providers: list[str] = Field(default_factory=list,
                                           description="BYOK 提供商注册表键名（无 'primary'）")
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict,
                                                 description="BYOK 提供商注册表")
    active_provider: str
    available_models: list[str] = Field(default_factory=list)
    active_model: str
    llm_configured: bool = False
    llm_unavailable_reason: str = Field(default="", description="未配置原因（已配置为空串）")
    agent_mode: str
    agent_max_retries: int
    agent_cr_model: str
    agent_in_model: str
    agent_gr_model: str
    agent_meta_model: str
    llm_structured_mode: str = Field(default="md_json", description="结构化输出模式")
    # ── 检索 / 健康 / 维护 / 日志 / WAL：v1.36 起全部可经 PUT /settings 修改并落盘 ──
    max_graph_hops: int
    rrf_k: int
    jaccard_threshold: float
    max_raw_content: int = Field(default=200000, description="单次 LLM 输入 raw_content 字符上限")
    health_check_interval: int
    health_check_timeout: int
    compensate_batch_size: int
    compensate_check_interval: int = 5
    agent_maintain_auto: bool = True
    agent_maintain_min_nodes: int = 10
    agent_maintain_max_nodes: int = 200
    agent_maintain_cooldown: int = 60
    agent_cmdmsg_max_rounds: int = 3
    agent_cr_skip_chars: int = 200
    log_level: str
    log_retention_days: int = 14
    log_jsonl: bool = False
    agent_logs_full: bool = True
    wal_checkpoint_interval: int = 300
    wal_checkpoint_bytes: int = 8388608
    # ── 保留策略（v1.39）：graph_ops 表与 trash/ 目录的有界化 ──
    graph_ops_retention: int = Field(
        default=5000, description="图层操作日志保留条数（压实，0 = 不压实）"
    )
    trash_retention_days: int = Field(
        default=30, description="回收站留档保留天数（已删数据的最后一份副本，0 = 永不清理）"
    )
    # ── 只读可见性（v1.36）：前端要能「穿透」看到后端到底把配置读成什么样 ──
    config_file: str = Field(default="", description="dpim.json 绝对路径（写到哪里）")
    log_dir: str = Field(default="", description="本地日志目录（env-only，只读显示）")
    config_sources: dict[str, str] = Field(
        default_factory=dict,
        description="取值来源：`env:DPIM_X`（环境变量顶掉，界面改不动）/ `file` / `default`",
    )


class ProviderModelsRequest(BaseModel):
    """POST /settings/models（v1.34）— 探测某提供商的可用模型列表。

    - `provider`：已登记条目名 → 地址/密钥取该条目（`api_key` 留空则用已存密钥）
    - `base_url` / `api_key`：未登记的新条目（弹窗里保存前先试）直接用提交值
    - `format`（v1.43）：接口格式（openai | responses | anthropic | custom）——
      决定探测方式：Anthropic 用 `x-api-key` + `anthropic-version` 打 `/models`，
      其余用 Bearer。留空 = 用已登记条目的格式（再缺省 openai）
    - `api_path` / `extra_headers`（v1.45）：**请求体优先**，其次已登记条目。
      补这两个是因为「草稿还没提交」的条目后端查不到：前端卡片上的「拉取模型」曾只发
      `provider` 名字，于是新条目一律报「未填模型地址（base_url）」——而地址就显示在卡片上
      （自定义格式的条目还会因缺额外请求头而 401）。
    """
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    format: str = ""
    api_path: str = ""
    extra_headers: dict[str, str] | None = None


class ProviderModelsResponse(BaseModel):
    """探测结果：`models` 为可用模型 id 列表；失败时 `error` 为服务端原文（可见失败）。"""
    models: list[str] = Field(default_factory=list)
    error: str = ""
    elapsed_ms: int = 0


class SettingsUpdateRequest(BaseModel):
    """PUT /settings 请求体 — 字段白名单 + 值域约束（与前端输入范围对齐）。

    安全语义：
    - 枚举字段（agent_mode / log_level）非法值直接 422，杜绝任意字符串注入运行时
    - providers[*].api_key 支持掩码幂等：提交掩码或空 = 保留现值
      （掩码格式 `xxx****xxxx`，见 core/security.py）
    - v1.34：不再接受 llm_* 主配置字段（已删除）；AI 身份经 `providers` 下发
    - v1.35：收到 llm_* 字段 → 422（不静默忽略）；`clear_api_key` 显式清空密钥
    - v1.36：**前端可配置面补齐**——检索 / 健康 / 维护 / 日志 / WAL 各项均可改并落盘
    """
    providers: dict[str, dict[str, Any]] | None = None
    active_provider: str | None = None
    active_model: str | None = None
    # 存储路径（v1.16）：可经前端修改，持久化 dpim.json，重启生效（数据文件不自动迁移）
    memory_db_path: str | None = None
    graph_json_path: str | None = None
    agent_mode: Literal["disabled", "pipeline"] | None = None
    agent_max_retries: int | None = Field(default=None, ge=0, le=10)
    agent_cr_model: str | None = None
    agent_in_model: str | None = None
    agent_gr_model: str | None = None
    agent_meta_model: str | None = None
    llm_structured_mode: Literal["md_json", "json", "tools"] | None = None
    max_graph_hops: int | None = Field(default=None, ge=1, le=5)
    rrf_k: int | None = Field(default=None, ge=1, le=200)
    jaccard_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    max_raw_content: int | None = Field(default=None, ge=1000, le=10_000_000)
    health_check_interval: int | None = Field(default=None, ge=10, le=86400)
    health_check_timeout: int | None = Field(default=None, ge=10, le=3600)
    compensate_batch_size: int | None = Field(default=None, ge=5, le=100)
    compensate_check_interval: int | None = Field(default=None, ge=1, le=3600)
    agent_maintain_auto: bool | None = None
    agent_maintain_min_nodes: int | None = Field(default=None, ge=1, le=100_000)
    agent_maintain_max_nodes: int | None = Field(default=None, ge=1, le=1_000_000)
    agent_maintain_cooldown: int | None = Field(default=None, ge=10, le=86400)
    agent_cmdmsg_max_rounds: int | None = Field(default=None, ge=1, le=10)
    agent_cr_skip_chars: int | None = Field(default=None, ge=0, le=100_000)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None
    log_retention_days: int | None = Field(default=None, ge=0, le=3650)
    log_jsonl: bool | None = None
    agent_logs_full: bool | None = None
    wal_checkpoint_interval: int | None = Field(default=None, ge=10, le=86400)
    wal_checkpoint_bytes: int | None = Field(default=None, ge=1_048_576, le=1_073_741_824)
    # 保留策略（v1.39）：0 = 关闭该项清理；上限给足（1e6 条 / 3650 天）
    graph_ops_retention: int | None = Field(default=None, ge=0, le=1_000_000)
    trash_retention_days: int | None = Field(default=None, ge=0, le=3650)


# ── 存储维护模型（P4：备份 / 校验 / 操作日志 / WAL 检查点）────────────────────


class BackupResponse(BaseModel):
    status: str = "ok"
    backup_dir: str
    stamp: str = ""
    pruned: int = 0
    manifest: dict[str, Any] = {}


class BackupListResponse(BaseModel):
    backups: list[dict[str, Any]] = []


class VerifyCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class VerifyResponse(BaseModel):
    ok: bool
    checks: list[VerifyCheck]
    sizes: dict[str, Any] = {}
    counts: dict[str, Any] = {}


class GraphOpItem(BaseModel):
    """图层操作日志条目（审计）：谁 / 何时 / 因何改了图。"""

    op_id: int
    created_at: str
    op_kind: str
    reason: str = ""
    actor: str = ""
    payload: dict[str, Any] = {}


class GraphOpListResponse(BaseModel):
    ops: list[GraphOpItem]
    total: int


class CheckpointResponse(BaseModel):
    status: str = "ok"
    busy: int = 0
    log_frames: int = 0
    checkpointed_frames: int = 0
    wal_bytes: int = 0


class RepoRefreshResponse(BaseModel):
    status: str = "ok"
    repo_id: str
    name: str = ""
    events: int = 0
    nodes: int = 0
    edges: int = 0
    reconcile_changed: int = 0
    last_reconcile_at: str = ""
    message: str = ""


class RepoRebuildResponse(BaseModel):
    """重建登记表（v1.31）：坏索引恢复入口，只扫盘重建登记，不删任何数据文件。"""

    message: str
    repos: int = 0
    # 重建前登记表是否处于「坏索引只读锁存」状态
    latched_before: bool = False


class RepoAdoptResponse(BaseModel):
    """收养既有目录（v1.32）：登记为 external 书目，`created` 列出实际补出来的文件名。"""

    repo_id: str
    message: str
    # 如 ["graph.json"]；一个都没补就是空列表
    created: list[str] = []


class RepoPurgeResponse(BaseModel):
    """清除书目（v1.31）：先备份再删文件，最后摘登记。"""

    message: str
    # 清除前的强制备份目录（外部库/无法备份时为空串，message 说明原因）
    backup_path: str = ""


# ── 本地日志（v1.31）：GET /logs、POST /logs/client ────────────────────────


class LogFileInfo(BaseModel):
    """单个日志文件（按天轮转的一份）。"""

    name: str
    kind: str = "backend"   # backend | frontend
    date: str = ""          # YYYY-MM-DD
    size: int = 0
    mtime: float = 0.0


class LogsResponse(BaseModel):
    """GET /logs：某个通道某一天的日志尾部 + 该通道全部可用文件。"""

    kind: str
    date: str = ""
    dir: str = ""
    files: list[LogFileInfo] = []
    lines: list[str] = []
    # 过滤后匹配行数超过 tail → true（返回的仍是**最新**的 tail 行）
    truncated: bool = False


class ClientLogRequest(BaseModel):
    """POST /logs/client：浏览器把前端日志送回本地文件。

    message 超出 8000 字符**截断**（不报错，日志不该因过长失败）；
    1_000_000 只是防超大请求体的兜底上限（与 IngestRequest.content 同档）。
    """

    level: Literal["debug", "info", "warning", "error"]
    message: str = Field(default="", max_length=1_000_000)
    source: str = Field(default="", max_length=200)


class ClientLogResponse(BaseModel):
    ok: bool = True


# ── 回收站（v1.31）：GET /trash、POST /trash/restore ──────────────────────


class TrashItem(BaseModel):
    kind: str          # event | node | graph
    id: str
    archived_at: str = ""
    size: int = 0
    # 留档内容里的标题/内容摘要（没有则空串）
    title: str = ""
    path: str = ""


class TrashListResponse(BaseModel):
    items: list[TrashItem] = []
    dir: str = ""


class TrashRestoreRequest(BaseModel):
    # graph = 整图留档（v1.42）：DELETE /graph 清空前自动留档，恢复为**合并式**补回
    kind: Literal["event", "node", "graph"]
    id: str = Field(min_length=1, max_length=200)


class TrashRestoreResponse(BaseModel):
    message: str
