// DPIM Spec 规约 - TypeScript 类型定义
// 版本 1.5 (BYOK 多模型网关 + Agent 管线配置 + 存图管线模型)
// 本文件定义所有广义接口：数据模型、Agent IO、内部消息、API 契约

// ==================== 基础枚举 ====================
export type EventType = 'interaction' | 'data' | 'source';
export type EventStatus = 'raw' | 'indexed' | 'linked' | 'failed' | 'skipped';
export type NodeType = 'system' | 'interaction' | 'data';
export type SourceFilter = 'all' | 'interaction' | 'data' | 'system';

/** Agent 角色（BYOK 角色路由 / 提示词文件映射） */
export type AgentRole = 'cr' | 'in' | 'gr' | 'meta';

/** Agent 管线开关：disabled（默认，无 Agent 降级态）| pipeline（四 Agent 管线） */
export type AgentMode = 'disabled' | 'pipeline';

/** 检索路径选择 */
export type SearchMethod = 'direct_search' | 'graph_query' | 'hybrid';

/** 分块类型标注 */
export type ChunkType = 'interaction' | 'data' | 'source' | 'ignore';

// ==================== 数据模型 ====================

/** 事件源证引用 */
export interface SourceRef {
  event_id: string;
  valid: boolean;
  hash: string;           // BLAKE3 前 16 位
}

/** 图节点元数据 */
export interface NodeMetadata {
  evidence_quote: string;  // 必填，源事件原文摘录
  tags?: string[];
  protected?: boolean;
  conflict?: boolean;
  [key: string]: unknown;
}

/** 图节点 */
export interface GraphNode {
  node_id: string;
  title: string;           // 不超过 60 字符
  content: string;
  node_type: NodeType;
  source_refs: SourceRef[];
  confidence: number;      // 0.0 ~ 1.0
  metadata: NodeMetadata;
}

/** 图边 */
export interface GraphEdge {
  source: string;          // 源节点 ID
  target: string;          // 目标节点 ID
  relation: string;        // 自然语言关系短语
  evidence_event_id: string; // 必填，来源事件 ID
  note?: string;
}

/** 信息线层事件（数据库完整记录） */
export interface Event {
  event_id: string;
  created_at: string;      // ISO8601
  raw_content: string;
  content_hash: string;
  event_type: EventType;
  status: EventStatus;
  graph_refs?: string[];   // 关联节点 ID 列表，数据库中为 JSON 数组
}

// ==================== Agent 输入输出 ====================

/** 信息处理 Agent 输出（已废弃，由 AnnotatedChunks 替代，暂保留兼容） */
export interface InformationFragment {
  interaction: string[];
  data: string[];
  source: string;          // 原始证据，无则为空字符串
}

/** 语义分块：必须是原文连续子串，不允许概括或改写 */
export interface SemanticChunk {
  content: string;          // 原文连续子串，不可增删改
  chunk_type: ChunkType;    // 分块类型标注
  label: string;            // 10 字以内中文标签
  confidence: number;       // 分类置信度 0.0-1.0
}

/** 信息管理 Agent 输出：带类型标注的原文分区（来源锚定，杜绝幻觉） */
export interface AnnotatedChunks {
  raw_content: string;      // 来源事件原始内容
  chunks: SemanticChunk[];
}

/** 中央控制 Agent 检索意图分析输出 */
export interface QueryIntent {
  method: SearchMethod;     // 检索路径选择
  keywords: string[];
  confidence: number;       // 0.0-1.0
}

/** BYOK 提供商实例配置（OpenAI 兼容协议） */
export interface ProviderConfig {
  name: string;             // provider 名称（'primary' = LLM_* 主配置）
  base_url: string;
  api_key: string;
  model: string;
  timeout: number;
}

/** 图构建 Agent - 新节点 */
export interface NodeCreate {
  title: string;
  content: string;
  node_type: 'interaction' | 'data';  // system 不可由 Agent 创建
  confidence: number;      // 初始置信度
  evidence_quote: string;  // 必填
}

/** 图构建 Agent - 新边 */
export interface EdgeCreate {
  source: string;          // 节点的 title 或已有 node_id
  target: string;
  relation: string;
  evidence_event_id: string;
}

/** 图构建 Agent 完整输出 */
export interface GraphBuildOutput {
  new_nodes: NodeCreate[];
  new_edges: EdgeCreate[];
  merged_into: string | null; // 若合并到已有节点，给出 node_id
}

/** 元认知审查问题项 */
export interface MetaCogIssue {
  type: 'hallucination' | 'illegal_edge' | 'conflict' | 'empty_node';
  description: string;
  suggestion: string;
}

/** 元认知裁判审查结果 */
export interface MetaCogVerdict {
  verdict: 'pass' | 'fail';
  issues: MetaCogIssue[];
}

// ==================== 内部队列消息 ====================

export type QueueMessageType =
  | 'ingest'
  | 'delete_event'
  | 'delete_node'
  | 'modify_node'
  | 'modify_edge'
  | 'modify_event_status'
  | 'query'          // 仅记录，实际同步处理
  | 'feedback'
  | 'timer_health'
  | 'compensate';

export interface QueueMessage {
  type: QueueMessageType;
  payload: Record<string, unknown>;
  timestamp: number;       // ms 时间戳
}

// 各消息 Payload 细化类型
export interface IngestPayload {
  event_id: string;
}

export interface DeleteEventPayload {
  event_id: string;
}

export interface DeleteNodePayload {
  node_id: string;
  force: boolean;
}

export interface ModifyNodePayload {
  node_id: string;
  new_content: string;
}

export interface ModifyEdgePayload {
  action: 'add' | 'remove';
  source: string;
  target: string;
  relation: string;
}

export interface ModifyEventStatusPayload {
  event_id: string;
  new_status: EventStatus;  // 允许的状态转换见 spec
}

export interface FeedbackPayload {
  result_id: string;
  accepted: boolean;
}

// ==================== API 请求 / 响应 ====================

// ---- 写入事件 ----
export interface IngestRequest {
  content: string;
  event_type?: EventType | 'auto';  // 默认 'auto'
}

export interface IngestResponse {
  event_id: string;
  status: EventStatus;
  message: string;
}

// ---- 删除事件 ----
export interface DeleteEventResponse {
  status: 'ok';
  message: string;
}

// ---- 删除节点 ----
export interface DeleteNodeRequest {
  force?: boolean;  // 默认 false
}

export interface DeleteNodeResponse {
  status: 'ok';
  message: string;
}

// ---- 修改节点 ----
export interface ModifyNodeRequest {
  content: string;
}

export interface ModifyNodeResponse {
  status: 'ok';
  node_id: string;
  message: string;
}

// ---- 修改事件状态 ----
export interface ModifyEventStatusRequest {
  status: EventStatus;
}

export interface ModifyEventStatusResponse {
  status: 'ok';
  event_id: string;
  new_status: EventStatus;
  message: string;
}

// ---- 修改事件内容 ----
export interface ModifyEventRequest {
  content: string;
}

export interface ModifyEventResponse {
  status: 'ok';
  event_id: string;
  message: string;
}

// ---- 检索 ----
export interface SearchRequest {
  query: string;
  source_filter?: SourceFilter;  // 默认 'all'
  max_hops?: number;            // 默认 2
  limit?: number;               // 默认 20
  offset?: number;              // 默认 0
}

export interface SearchResult {
  node_id: string;
  title: string;
  snippet: string;
  score: number;
  source_events: string[];
  source_type: EventType | 'system'; // 可能值: interaction, data, source, system
  confidence: number;
  degraded: boolean;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  degraded: boolean;
}

// ---- 反馈 ----
export interface FeedbackRequest {
  result_id: string;
  accepted: boolean;
}

export interface FeedbackResponse {
  status: 'ok';
  message: string;
}

// ---- 健康检查 ----
export interface LayerStats {
  total_events?: number;
  status_raw?: number;
  status_indexed?: number;
  status_linked?: number;
  status_failed?: number;
  status_skipped?: number;
  total_nodes?: number;
  system_nodes?: number;
  interaction_nodes?: number;
  data_nodes?: number;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  ai_available: boolean;
  layers: {
    event_line: LayerStats;
    knowledge_graph: LayerStats;
  };
  last_event_at: string;  // ISO8601
  version: string;
}

// ---- 通用错误 ----
export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

// ==================== 状态校验密钥 ====================

/** 状态校验密钥响应 (GET /state-hash)
 *  后端返回 UUID 字符串作为数据版本标识。
 *  前端在写操作提交前比对，一致则允许提交，不一致则拒绝并提示刷新。
 */
export interface StateHashResponse {
  hash: string;            // UUID 状态校验密钥
  changed_at: string;      // 最近变更时间 (ISO8601)
}

// ==================== 分页列表（dpim-webui）====================

/** 通用分页结构 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** 事件列表摘要项 (GET /events) */
export interface EventListItem {
  event_id: string;
  created_at: string;
  raw_content: string;     // 截断显示
  event_type: EventType;
  status: EventStatus;
}

/** 事件详情 (GET /events/{event_id}) */
export interface EventDetail extends Event {}

/** 节点列表摘要项 (GET /nodes) */
export interface NodeListItem {
  node_id: string;
  title: string;
  node_type: NodeType;
  confidence: number;
}

/** 节点详情 (GET /nodes/{node_id}) */
export interface NodeDetail extends GraphNode {
  edges: GraphEdge[];      // 该节点参与的所有边（出边 + 入边）
}

// ==================== 配置（dpim-webui）====================

/** 配置项响应 (GET /settings) */
export interface SettingsResponse {
  memory_db_path: string;
  graph_json_path: string;
  llm_base_url: string;
  llm_api_key: string;
  llm_model_name: string;
  llm_timeout: number;
  available_providers: string[];  // 可选 provider 名单（含 'primary'）
  providers: Record<string, { base_url: string; api_key: string; model?: string; models?: string[]; timeout?: number }>;
  active_provider: string;      // BYOK 活动 provider（默认 'primary'）
  available_models: string[];   // 活动 provider 的模型列表（供「使用」选择）
  active_model: string;         // 使用中的模型（空 → provider 首个/默认）
  agent_mode: AgentMode;        // 管线开关
  agent_max_retries: number;    // Meta 驳回最大修正轮次
  agent_cr_model: string;       // 空值 = 回退活动 provider 默认模型
  agent_in_model: string;
  agent_gr_model: string;
  agent_meta_model: string;
  max_graph_hops: number;
  rrf_k: number;
  jaccard_threshold: number;
  health_check_interval: number;
  compensate_batch_size: number;
  log_level: string;
}

/** 配置更新请求 (PUT /settings) 只下发需要修改的字段即可 */
export interface SettingsRequest {
  llm_base_url?: string;
  llm_api_key?: string;
  llm_model_name?: string;
  llm_timeout?: number;
  providers?: Record<string, { base_url: string; api_key: string; model?: string; models?: string[]; timeout?: number }>;
  active_provider?: string;
  active_model?: string;
  agent_mode?: AgentMode;
  agent_max_retries?: number;
  agent_cr_model?: string;
  agent_in_model?: string;
  agent_gr_model?: string;
  agent_meta_model?: string;
  max_graph_hops?: number;
  rrf_k?: number;
  jaccard_threshold?: number;
  health_check_interval?: number;
  compensate_batch_size?: number;
  log_level?: string;
}

// ==================== 配置项（类型参考）====================
export interface DPIMConfig {
  MEMORY_DB_PATH: string;
  GRAPH_JSON_PATH: string;
  LLM_BASE_URL: string;
  LLM_API_KEY: string;
  LLM_MODEL_NAME: string;
  LLM_TIMEOUT: number;
  // BYOK 多模型网关
  PROVIDERS?: string;           // JSON dict：{name: {base_url, api_key, model, timeout}}
  ACTIVE_PROVIDER: string;      // 默认 'primary'
  // Agent 管线
  AGENT_MODE: AgentMode;        // 默认 'disabled'
  AGENT_MAX_RETRIES: number;    // 默认 2
  MAX_RAW_CONTENT: number;      // 上下文护栏：单次 LLM 输入中 raw_content 最大字符数（默认 10000）
  AGENT_CR_MODEL: string;
  AGENT_IN_MODEL: string;
  AGENT_GR_MODEL: string;
  AGENT_META_MODEL: string;
  MAX_GRAPH_HOPS: number;
  RRF_K: number;
  JACCARD_THRESHOLD: number;
  HEALTH_CHECK_INTERVAL: number;
  COMPENSATE_BATCH_SIZE: number;
  LOG_LEVEL: string;
}
