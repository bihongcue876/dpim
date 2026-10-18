// DPIM Spec 规约 - TypeScript 类型定义
// 版本 1.46 (系统性审计（5 路：密钥外泄 / 草稿错位 / 静默失败 / 契约一致性 / 边界细节）后修的第一批：① **错误原文不得回显密钥**——httpx/h11 的 `Illegal header value b'…'` 会原样带上整条请求头值（含真钥，实测 `api_key` 含换行时复现），故请求头值先 `sanitize_secret()` 清控制字符、异常原文在交给界面/落盘前过 `scrub_secrets()`（探测端点、健康检查日志与降级原因三处）；② **`reconcile_changed` 不再恒 0**——`refresh_repo()` 返回的键是 `changed` 而模型要 `reconcile_changed`，Pydantic `extra='ignore'` 把真值静默丢掉（「刷新修复」永远报「源证对账变更 0 条」），router 补映射 + 句首文案；③ 类型修正：`ClearGraphResponse` 补齐 v1.42 的 7 个字段（原停在 status/message，前端绕开自写类型 = 下一次「类型在骗人」的引信）、`LLMCallLog.input`（`full=true` 时后端下发的是 `input`，不是 `input_preview`）。端点仍 45)
// 版本 1.45 (AI 可用性判定与 BYOK 界面三处真缺陷：① LLM 健康检查改按接口格式分流（旧实现走 OpenAI SDK 的 client.models.list() → 对 format=anthropic 的 provider 永远发 Bearer → 真 Anthropic / OpenCode Zen 回 401 → AI 被误判「连不上」，降级/补偿/自动维护永不启动）；② POST /settings/models 增 api_path / extra_headers（请求体优先 → 已登记条目），让「草稿还没提交」的条目也能探测；③ 前端草稿只存**掩码**密钥（明文只活在输入框与待提交暂存，提交时才下发）——旧实现把明文写进草稿，卡片与弹窗占位符都显示明文。端点仍 45)
// 版本 1.44 (Anthropic 的 max_tokens 与思考预算不再互相打架：Anthropic 要求 max_tokens 严格大于 thinking.budget_tokens 且思考 token 计入 max_tokens —— 旧实现「先定死上限再算 thinking」会让「预算 8192 + 未填上限」发出 4096<8192 而必定 400；现改为定上限（条目 → 全局 → 兜底 4096）→ 算 thinking → 余量不足则抬到「预算 + 1024」并 WARNING 留痕。另修优先级：enable_thinking=false（显式关）压过残留 thinking_budget（旧顺序会让「关掉思考」被无声推翻、还连带丢掉 temperature）。界面把实际生效值说出来（弹窗提示 + 卡片显示「默认（4096）」/「2048（思考预算更大，实际按 5120）」）。端点仍 45、字段无增删)
// 版本 1.43 (接口格式：provider 条目增 format（openai|responses|anthropic|custom）/ api_path / extra_headers —— 网关按格式分派（openai/responses 走 instructor，anthropic/custom 走 httpx 适配：x-api-key + anthropic-version + max_tokens 必填 + JSON 校验回喂重问）；POST /settings/models 增 format，探测按格式分流；端点仍 45)
// 版本 1.42 (图层一致性：add_edge 拒绝未知端点（不再由 NetworkX 自动造出无 data 的空壳节点）+ graph.json 里的悬空边加载时跳过并落盘清除 + verify 新增 no_dangling_edges_in_file + DELETE /graph 清空前整图留档到 trash/graphs/（kind=graph 合并式恢复）并把线层派生链接一并撤销（清 graph_refs + linked→indexed，故白名单增 linked→indexed）+ graph_ops 的 edge_delete 携带被删边原数据；端点仍 45)
// 版本 1.41 (GET /health 分层统计键名明确 + 前端契约类型修正：layers.event_line 实际是 {total_events, raw, indexed, linked, failed, skipped}、layers.knowledge_graph 是 {total_nodes, system, interaction, data}；旧 LayerStats 声明的 status_* / system_nodes 等键后端从未下发过 → 概览台四个分项恒显示「—」而 vue-tsc 无感。现拆为 EventLineStats / GraphLayerStats 真实形状；端点仍 45)
// 版本 1.40 (联合节点列表的 node_type 口径修正：GET /nodes?repo_ids=… 此前用 str(枚举) 拼响应 → Python 3.11+ 得到 "NodeType.data"，与单库路径的 "data" 不同口径，前端「全部书目」下按类型筛选全部失配；现统一取值文本；端点仍 45)
// 版本 1.39 (保留策略：GRAPH_OPS_RETENTION 默认 5000（graph_ops 超限走「压实」= 最老明细换成等价快照 op，replay 前后一致，恢复能力与体检口径不变）+ TRASH_RETENTION_DAYS 默认 30 天（0 = 永不清理，按文件 mtime 清 trash/{events,nodes,graphs}/ 与 trash/restored/）；启动跑一轮后并入存储卫生循环、最多每小时一次；两项进 GET/PUT /settings 并落盘 dpim.json 的 storage 段；端点仍 45)
// 版本 1.38 (多库自动维护口径归一：AI 恢复后的顺带整理此前只入队一条不带 repo_id 的消息 → 回退默认库，等于只有默认库能被自动整理；现逐受管库各入队一次并带 repo_id，规模闸门唯一留在 orchestrator；端点仍 45)
// 版本 1.37 (边列表端点 GET /edges（+1 端点，44→45）：node_id 两侧命中 / source / target / relation 筛选，repo_id 或 repo_ids 联合（按 (source,target) 去重 + 首命中库归属），limit 默认 200、0..5000 越界 400、offset 负数 400，按 (source,target) 稳定排序；图谱页取边由「逐节点取详情」改为一次请求；顺带纠正 §8.2 分页约定为真实口径)
// 版本 1.36 (前端可配置面补齐 + 来源可见：6 项「只改内存」（max_graph_hops / rrf_k / jaccard_threshold / health_check_interval / health_check_timeout / compensate_batch_size）修复为 env → dpim.json → 内置默认并落盘；+14 可配置字段；GET /settings 增 config_sources / config_file / log_dir，被 env 顶掉的项 PUT 不写入内存并回 ignored_by_env；端点仍 44)
// 版本 1.35 (BYOK 前端可调性补完：提交已移除的 llm_* 字段由静默忽略改为 422（否则界面显示「已保存」而一个字段都没改）+ providers[*].clear_api_key: true = 显式清空密钥（PUT 专用、不入库、GET 从不下发）；端点仍 44)
// 版本 1.34 (AI 配置归一：删掉主 provider（primary）特殊分支与全部身份默认值（此前内置 LLM_BASE_URL=localhost:11434 + llama3:8b，未配置的部署会静默指向不存在的本地 llama）；AI 身份只在 providers 条目里；未配置 ≠ 降级（GET /health 三态 ok|unconfigured|degraded + ai_unavailable_reason）；GET /settings 删 7 个 llm_* 字段、增 llm_configured / llm_unavailable_reason；+1 端点 POST /settings/models（联网探测模型列表），43→44)
// 版本 1.33 (主 provider（BYOK）配置持久化修复：PUT /settings 的 7 个 llm_* 此前只改内存（save_dpim_config 不写、读取链只读 env）→ 重启静默退回内置默认；现 dpim.json 增 llm 段，读写链 env → dpim.json → 内置默认；并让掩码形状的值绝不落库（looks_like_mask）；端点仍 43)
// 版本 1.32 (书目收养（POST /repos/adopt：目录里至少有一个库文件即可登记为 external，缺 memory.db 补空库、缺 graph.json 补空图并顺带尝试从 graph_ops 重放恢复；只补空件不覆盖；重复登记 409、一个文件都没有 400）+ 书目未加载原因可见（RepoInfo.load_error）+ POST /agent/maintain 补 mode 请求体（compress|update，默认 update；此前不读 body → 选 update 实际走 compress）+ health_check_timeout 契约补齐；+1 端点，43 端点)
// 版本 1.31 (本地日志接口（GET /logs 按通道/日期/级别/关键词翻看尾部 + POST /logs/client 浏览器日志回传）+ 回收站接口（GET /trash 留档清单 + POST /trash/restore 按原 id 恢复事件/节点并尽力恢复留档边，恢复后留档移入 trash/restored/）+ POST /repos/rebuild 登记表重建（坏索引恢复，不删数据）+ POST /repos/{id}/purge 书目清除（先备份再删文件）+ PUT /repos/{id} 增 root 外部库重指向 + 事件/节点列表项增来源库归属 repo_id/repo_name；+6 端点，42 端点)
// 版本 1.30 (存储保障：graph_ops 操作日志与重放恢复 / graph.json format_version / 多代备份 / 备份·校验·审计端点（+6，36 端点）/ 跨进程单实例锁 / 回收站留档 / WAL 检查点 + 本地日志系统（前后端分文件按天轮转）+ 联合检索修正（每库候选池 + 分页只切一次 + 融合轨迹 trace）+ 库作用域贯穿（feedback / events{id} / nodes{id} / 指令 / agent 维护与补偿）+ 事件与节点联合列表 repo_ids + 术语修正「不可变日志」→「时序事件存储」)
// 版本 1.29 (对话指令系统 + 同源聚合 + 节点语义与源证管理 + 连通性治理 + ^update 两阶段优化 + 待连线对候选 + 事件关联节点实时派生 + ^cmdmsg 指令消息多轮 + 存储修复（图层损坏留档/合并上限/FTS 自愈/失败原因落库/skipped 检索排除）+ 库与分组（一库 = 一 db + 一 json，repos/index.json 登记表，受管开关，联合检索等权 RRF 去重锚定，+7 库端点，30 端点）+ Cr 短路)
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
  hash: string;           // BLAKE2s-8B（16 字符十六进制）
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
  name: string;             // provider 名称（v1.34：注册表键名，'primary' 不再特殊）
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
  type: 'hallucination' | 'illegal_edge' | 'conflict' | 'empty_node' | 'redundant_node';
  description: string;
  suggestion: string;
}

/** 元认知裁判审查结果 */
export interface MetaCogVerdict {
  verdict: 'pass' | 'fail';
  issues: MetaCogIssue[];
}

// ==================== 图维护（调整/合并/删改）====================

/** 维护合并：target 吸收 source_ids（源证/内容/边）后删除 source */
export interface MaintenanceMerge {
  target_id: string;
  source_ids: string[];
  reason?: string;
}

/** 维护删除 */
export interface MaintenanceDelete {
  node_id: string;
  reason?: string;
}

/** 维护修改：interaction 覆盖内容；data 由执行层转为追加行 */
export interface MaintenanceUpdate {
  node_id: string;
  content: string;
  reason?: string;
}

/** 维护删边 */
export interface MaintenanceEdgeRemove {
  source: string;
  target: string;
  relation?: string;
  reason?: string;
}

/** 维护压缩补边：把概括后可能丢失的隐含关系显式化为边 */
export interface MaintenanceEdgeAdd {
  source: string;
  target: string;
  relation: string;
  reason?: string;
}

/** v1.24：update 模式补缺失要点（锚定已有事件，quote 为原文连续子串） */
export interface MaintenanceNodeAdd {
  title: string;          // ≤60 字符
  content: string;
  node_type: 'interaction' | 'data';  // system 禁止
  event_id: string;       // 锚定的已有事件
  evidence_quote: string; // 事件原文连续子串（本地硬校验）
  parent_node_id?: string; // 可选：挂为该节点子节点（subtopic_of 边）
  reason?: string;
}

/** 维护压缩：仅 data 节点概括覆盖 content + 可选精炼 title + 可选补边 */
export interface MaintenanceCompress {
  node_id: string;
  content: string;
  title?: string;
  new_edges?: MaintenanceEdgeAdd[];
  reason?: string;
}

/** 图维护计划（Gr 产出 → Meta 审核 → 执行；空计划合法） */
export interface GraphMaintenancePlan {
  merges: MaintenanceMerge[];
  deletes: MaintenanceDelete[];
  updates: MaintenanceUpdate[];
  edge_removes: MaintenanceEdgeRemove[];
  edge_adds?: MaintenanceEdgeAdd[];   // v1.23：把孤立节点连回图
  node_adds?: MaintenanceNodeAdd[];   // v1.24：update 模式补缺失要点
  compresses: MaintenanceCompress[];
  confidence: number;
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
  | 'compensate'
  | 'maintain_graph';

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
  event_type: EventType;  // v1.17：必填枚举，auto 模式已移除
  repo_id?: string;       // v1.29：目标册，缺省活动库
}

export interface IngestResponse {
  event_id: string;
  status: EventStatus;
  message: string;
  /** v1.20：对话指令（/压缩 /merge /delete /data: /node 等）触发时为 true；
   *  未创建事件时 event_id=""、status="skipped"，message 携带面向用户的执行结果 */
  command_triggered: boolean;
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
  /** 修改内容（可选；system 节点禁止） */
  content?: string;
  /** v1.22：追加源事件（幂等，事件须存在） */
  add_source_event_id?: string;
  /** v1.22：移除源事件（移除后须仍保留 ≥1 条有效源证，否则 409） */
  remove_source_event_id?: string;
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
  event_type?: EventType;  // v1.17：可选类型修订，缺省保持不变（仅改线层，不联动图节点）
}

export interface ModifyEventResponse {
  status: 'ok';
  event_id: string;
  message: string;
}

// ---- 创建节点 ----
export interface CreateNodeRequest {
  title: string;            // ≤60 字符
  content?: string;         // 缺省等于 title
  node_type?: NodeType;     // 默认 'data'
  source_event_id?: string; // 可选，关联来源事件 ID
}
export interface CreateNodeResponse {
  status: 'ok';
  node_id: string;
  message: string;
}

// ---- 检索 ----
export interface SearchRequest {
  query: string;
  source_filter?: SourceFilter;  // 默认 'all'
  max_hops?: number;            // 默认 2；0 = 不扩散（事件原文/知识节点纯检索），1-5 = 扩散跳数（v1.18）
  limit?: number;               // 默认 20
  offset?: number;              // 默认 0
  repo_ids?: string[];          // v1.29：缺省 = 全部受管库（联合检索）；单值 = 指定册；多值 = 限定联合
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
  kind?: 'node' | 'event';      // v1.29：结果种类（联合检索去重键依赖）
  repo_id?: string;             // v1.29：来源册（联合去重合并时 = 首命中册）
  repo_name?: string;           // v1.29：来源库名
  source_repos?: string[];      // v1.29：被去重合并项的全部来源库名
  content_hash?: string;        // v1.29：事件内容哈希（仅 kind=event）
}

/** v1.30：联合检索融合轨迹——单条结果在各库的排名 / 原始分 / RRF 贡献 */
export interface JointContribution {
  repo_id: string;
  repo_name: string;
  rank: number;
  score: number;
  rrf: number;
}

export interface JointHitTrace {
  node_id: string;
  title: string;
  kind: 'node' | 'event';
  repo_id: string;
  repo_name: string;
  source_repos: string[];
  contributions: JointContribution[];
}

export interface JointRepoTrace {
  repo_id: string;
  repo_name: string;
  candidates: number;
  elapsed_ms: number;
}

export interface JointTrace {
  candidate_pool: number;   // 每库取的候选池大小（limit×3，下限 50）
  merged_total: number;     // 融合去重后总数（= total）
  deduped: number;          // 被去重合并的条目数
  elapsed_ms: number;
  per_repo: JointRepoTrace[];
  hits: JointHitTrace[];    // 只含本页结果
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  degraded: boolean;
  /** v1.30：联合检索融合轨迹；单库检索为 null */
  trace?: JointTrace | null;
}

// ---- 反馈 ----
export interface FeedbackRequest {
  result_id: string;
  accepted: boolean;
  /** v1.30：库作用域（缺省 = 活动库）；跨库结果必须带上，否则反馈静默落在活动库 */
  repo_id?: string;
}

export interface FeedbackResponse {
  status: 'ok';
  message: string;
}

// ---- 清空图谱 ----
/** `DELETE /graph` 的响应（v1.42 起语义扩展：**清空前先整图留档** + 撤销线层派生链接）。
 *
 *  ⚠️ 这个类型曾停在 v1.42 之前（只有 status/message），而前端 `api/nodes.ts` 绕开它自写了
 *  7 字段类型——**这是「类型在骗人」的同一类陷阱**：哪天有人顺手改成 `import type { ClearGraphResponse }`，
 *  `res.archived` / 计数就全读不到，而 `vue-tsc` 不会报错（清空图层的「留档失败 = 不可恢复」
 *  提示会静默退回快乐路径）。故补齐为真实形状。 */
export interface ClearGraphResponse {
  status: 'ok';
  message: string;
  /** 是否已把整图留档到 `trash/graphs/`（false = 留档失败，此操作不可恢复） */
  archived: boolean;
  /** 留档文件名（`graph-<时间戳>.json`）；未留档为空串 */
  archive_id: string;
  cleared_nodes: number;
  cleared_edges: number;
  /** 被撤销派生链接（`linked → indexed`）的事件数 */
  unlinked_events: number;
  /** 清掉 `graph_refs` 的事件数 */
  relinked_events: number;
}

// ---- AI 调用日志（GET /agent/logs）----
export interface LLMCallLog {
  role: string;            // cr | in | gr | meta
  model: string;
  timestamp: number;       // Unix 时间戳（秒）
  input_preview: string;   // LLM 输入前 2000 字符（**仅 full=false 的摘要分支**下发）
  /** v1.46：`full=true`（取全文）时后端直接 `log.__dict__`，字段名是 **`input`**、
   *  **没有 `input_preview`** —— 旧前端只读 `input_preview` → 开「取全文」后输入区恒空白，
   *  看起来像模型没收到输入（而这正是排查 401 / 健康检查失败时最需要看的一栏）。
   *  读取处用 `input_preview ?? input`。 */
  input?: string;
  output: string;          // LLM 输出前 2000 字符
  error: string;           // 空字符串 = 成功
}
export interface AgentLogsResponse {
  logs: LLMCallLog[];
}

// ---- 手动补偿（POST /agent/compensate）----
export interface CompensateResponse {
  status: 'ok';
  message: string;
}

// ---- 健康检查 ----
/** `/health` 的线层统计（**键名以实际下发为准**，v1.41 修正）。
 *
 * 此前这里写的是 `status_raw` / `status_indexed` / `status_linked` / `status_failed` /
 * `status_skipped` —— 后端**从来没有**这么下发过（它下发的是 `raw` / `indexed` /
 * `linked` / `failed` / `skipped`）。于是**类型在骗人**：概览台照着类型写了
 * `health.eventLine.status_linked`，四个分项恒显示「—」，而 `vue-tsc` 毫无反应
 * （类型允许错的键、反过来禁止正确的键）。链 AE 补页面级单测时抓到。
 */
export interface EventLineStats {
  total_events?: number;
  raw?: number;
  indexed?: number;
  linked?: number;
  failed?: number;
  skipped?: number;
}

/** `/health` 的图层统计（键名同样以实际下发为准：`system` / `interaction` / `data`） */
export interface GraphLayerStats {
  total_nodes?: number;
  system?: number;
  interaction?: number;
  data?: number;
}

export interface HealthResponse {
  /** v1.34 三态：ok（AI 可用）/ unconfigured（**没配 AI**，无 AI 模式的正常态）/ degraded（配了但连不上） */
  status: 'ok' | 'unconfigured' | 'degraded';
  ai_available: boolean;
  /** v1.34：不可用原因（未配置原因优先，否则最近一次连接失败原因）；可用为空串 */
  ai_unavailable_reason?: string;
  layers: {
    event_line: EventLineStats;
    knowledge_graph: GraphLayerStats;
  };
  last_event_at: string;  // ISO8601
  version: string;
  /** v1.29：队列与册可见性 */
  queue_depth?: number;
  worker_running?: boolean;
  active_repo_id?: string;
  /** v1.30：存储容量与备份（db/wal/json 体积、备份份数、操作日志条数） */
  storage?: {
    db_bytes: number;
    wal_bytes: number;
    json_bytes: number;
    backups: number;
    graph_ops: number;
  };
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

/** 事件列表摘要项 (GET /events；v1.19 支持可选 query 关键词检索，可叠加 status/type 过滤) */
export interface EventListItem {
  event_id: string;
  created_at: string;
  raw_content: string;     // 截断显示
  event_type: EventType;
  status: EventStatus;
  error?: string;          // v1.28：失败原因（脱敏摘要，仅 failed 非空）
  /** v1.31：来源库归属（联合列表必须知道每行来自哪个库；单库查询填该库） */
  repo_id?: string;
  repo_name?: string;
}

// ==================== 库与分组（v1.29）====================

/** 一库 = 一 memory.db + 一 graph.json；书库 = 文件夹分组 */
export interface RepoInfo {
  repo_id: string;
  name: string;
  note: string;
  group: string | null;      // 书库展示名（不入路径）
  root_kind: 'managed' | 'external';
  managed: boolean;          // 受管开关：false = 休眠（不加载不检索不构图）
  active: boolean;           // 是否活动库
  loaded: boolean;           // 是否已加载
  /** v1.32：未加载原因（加载失败原因优先；否则休眠 / 库目录不存在 / 登记文件缺失）；已加载为空串 */
  load_error?: string;
  total_events: number | null;
  total_nodes: number | null;
  db_path: string;
  json_path: string;
  created_at: string;
  updated_at: string;
}

export interface RepoListResponse {
  repos: RepoInfo[];
  active_repo_id: string;
}

export interface RepoCreateRequest {
  name: string;              // 1-80 字
  note?: string;             // ≤500 字
  group?: string;            // 书库展示名（可选分组）
  root_kind?: 'managed' | 'external';  // 默认 managed
  root?: string;             // external 必填：已存在目录（含 memory.db + graph.json）
}

/** POST /repos/adopt（v1.32）：收养既有目录——目录里至少有一个库文件即可登记为 external */
export interface RepoAdoptRequest {
  root: string;              // 已存在目录（绝对路径；禁设清单照旧生效）
  name: string;              // 1-80 字
  note?: string;             // ≤500 字
  group?: string;            // 书库展示名
  adopt_missing?: boolean;   // 默认 true = 缺哪个补哪个（只补空件，绝不覆盖已有文件）
}

export interface RepoAdoptResponse {
  repo_id: string;
  message: string;
  created: string[];         // 实际补出来的文件名，如 ['graph.json']；一个都没补为空数组
}

export interface RepoUpdateRequest {
  name?: string;
  note?: string;
  group?: string;
  managed?: boolean;         // 受管开关，切换即时生效
  /** v1.31：外部库重指向（换目录，须含 memory.db + graph.json）；受管库传 root → 400 */
  root?: string;
}

/** 事件详情 (GET /events/{event_id}) */
export interface EventDetail extends Event {}

/** 节点列表摘要项 (GET /nodes；v1.19 支持可选 query 关键词检索，可叠加 type 过滤) */
export interface NodeListItem {
  node_id: string;
  title: string;
  node_type: NodeType;
  confidence: number;
  /** v1.31：来源库归属（同 EventListItem） */
  repo_id?: string;
  repo_name?: string;
}

/** 节点详情 (GET /nodes/{node_id}) */
export interface NodeDetail extends GraphNode {
  edges: GraphEdge[];      // 该节点参与的所有边（出边 + 入边）
}

/** 边列表项 (GET /edges，v1.37)：GraphEdge + 来源库归属（联合列表用，同 NodeListItem） */
export interface EdgeListItem extends GraphEdge {
  repo_id?: string;
  repo_name?: string;
}

/** 边列表响应 (GET /edges，v1.37)：按 (source, target) 稳定排序，故分页可复现 */
export interface EdgeListResponse {
  items: EdgeListItem[];
  total: number;
  limit: number;
  offset: number;
}

// ==================== 配置（dpim-webui）====================

/** 配置项响应 (GET /settings) */

/** LLM 接口格式（v1.43）：一个 provider 条目 = 一套协议。
 *  - `openai`（默认，老条目零迁移）：`POST {base}/chat/completions`，`Authorization: Bearer`
 *  - `responses`：`POST {base}/responses` —— body 用 `input` / `max_output_tokens` /
 *    `text.format`，结构化输出走工具调用（instructor RESPONSES_TOOLS）
 *  - `anthropic`：`POST {base}/messages` —— `x-api-key` + `anthropic-version` 头，
 *    `system` 是顶层字段、`max_tokens` 必填（未填按 4096 兜底；v1.44：思考 token 计入它，
 *    余量不足时后端自动抬到「思考预算 + 1024」，否则会被 400 或截断）
 *  - `custom`：自定路径（`api_path`）与额外请求头，仍按 chat completions 形状收发 */
export type ProviderFormat = 'openai' | 'responses' | 'anthropic' | 'custom';

/** BYOK provider 条目：基础连接 + 接口格式 + 厂商适配参数（api_key 经 GET /settings 下发为掩码值 `{前3}****{后4}`） */
export interface ProviderEntry {
  base_url: string;
  api_key: string;               // GET 下发为掩码；PUT 提交掩码/空 = 保留现值
  /** v1.35：PUT 专用标记——`true` = **显式清空**该条目已存密钥（`api_key` 置空）。
   *  「空串 = 保持现值」使已存密钥无法从前端清掉（只能删条目重建），故清空必须单独声明；
   *  解析后该标记**不入库**（GET /settings 从不下发它） */
  clear_api_key?: boolean;
  /** v1.43：接口格式（缺省 openai）；决定网关走哪套协议与探测用哪套鉴权头 */
  format?: ProviderFormat;
  /** v1.43：自定义请求路径（仅 custom 有意义；缺省 /chat/completions，未写前导 `/` 会自动补） */
  api_path?: string;
  /** v1.43：额外 HTTP 请求头（各格式通用，如自建网关的鉴权头） */
  extra_headers?: Record<string, string>;
  model?: string;              // 旧式单模型
  models?: string[];           // 多模型列表
  timeout?: number;
  max_tokens?: number;         // 输出 token 上限（0 = 服务端默认；anthropic 必填，未填按 4096 兜底——
                               // v1.44：它是**上限**不是目标长度，按实际输出计费；开了思考时思考 token
                               // 也计入，且 anthropic 要求它严格大于 thinking_budget，余量不足时后端会
                               // 自动抬到「预算 + 1024」并 WARNING 留痕）
  enable_thinking?: boolean;   // 思考开关（缺省 = 服务端默认；anthropic 映射到 thinking。
                               // v1.44：显式 false **压过**残留的 thinking_budget——关就是关）
  thinking_budget?: number;    // 思考预算 tokens（0 = 不设；anthropic 映射到 budget_tokens，计入 max_tokens）
  thinking_style?: string;     // auto | top_level | chat_template_kwargs（仅 openai 格式）
  extra_body?: Record<string, unknown>;  // 任意厂商参数透传
  structured_mode?: string;    // md_json | json | tools（仅 openai 格式）
}

export interface SettingsResponse {
  memory_db_path: string;
  graph_json_path: string;
  available_providers: string[];  // v1.34：注册表键名（不再有 'primary' 兜底）
  providers: Record<string, ProviderEntry>;
  active_provider: string;      // 活动 provider（空 = 未选择）
  available_models: string[];   // 活动 provider 的模型列表（供「使用中的模型」选择）
  active_model: string;         // 使用中的模型（空 → provider 列表首个）
  /** v1.34：是否具备 AI 调用条件（提供商 + 地址 + 模型齐备） */
  llm_configured: boolean;
  /** v1.34：未配置原因（中文，可直接展示）；已配置为空串 */
  llm_unavailable_reason: string;
  agent_mode: AgentMode;        // 管线开关
  agent_max_retries: number;    // Meta 驳回最大修正轮次
  agent_cr_model: string;       // 空值 = 回退活动 provider 默认模型
  agent_in_model: string;
  agent_gr_model: string;
  agent_meta_model: string;
  /** v1.36：结构化输出模式（md_json | json | tools）；provider 条目可覆盖 */
  llm_structured_mode: string;
  max_graph_hops: number;
  rrf_k: number;
  jaccard_threshold: number;
  /** v1.36：单次 LLM 输入 raw_content 字符上限（上下文护栏） */
  max_raw_content: number;
  health_check_interval: number;
  /** v1.32：健康检查超时（秒，与生成超时分离）。此前只存在于后端契约（core/models.py），TS 侧缺失 */
  health_check_timeout?: number | null;
  compensate_batch_size: number;
  /** v1.36：补偿批次结果检查间隔（秒） */
  compensate_check_interval: number;
  /** v1.36：图维护自动触发与高水位 */
  agent_maintain_auto: boolean;
  agent_maintain_min_nodes: number;
  agent_maintain_max_nodes: number;
  agent_maintain_cooldown: number;
  /** v1.36：^cmdmsg 多轮封顶 / Cr 短路阈值（0 = 关闭短路） */
  agent_cmdmsg_max_rounds: number;
  agent_cr_skip_chars: number;
  log_level: string;
  /** v1.36：本地日志与 WAL 治理 */
  log_retention_days: number;
  log_jsonl: boolean;
  agent_logs_full: boolean;
  wal_checkpoint_interval: number;
  wal_checkpoint_bytes: number;
  /** v1.39：保留策略——graph_ops 表与 trash/ 目录的有界化 */
  graph_ops_retention: number;      // 图层操作日志保留条数（压实，0 = 不压实）
  trash_retention_days: number;     // 回收站留档保留天数（0 = 永不清理）
  /** v1.36：只读可见性——配置写到哪个文件、日志落在哪个目录 */
  config_file: string;
  log_dir: string;
  /** v1.36：各配置项取值来源：`env:DPIM_X`（环境变量顶掉，界面改不动）/ `file` / `default`。
   *  前端据此对锁定项显示提示——否则「界面改了没效果」又是一次静默失败 */
  config_sources: Record<string, string>;
}

/** 模型探测请求 (POST /settings/models，v1.34；v1.43 增 format；v1.45 增 api_path/extra_headers)：
 *  拉取某提供商的可用模型列表。
 *  - 已登记条目：传 `provider`，地址/密钥取该条目（`api_key` 留空 = 用已存密钥）
 *  - 新条目（保存前先试）：传 `base_url` + `api_key`
 *  - `format`：决定探测方式（anthropic 用 `x-api-key` + `anthropic-version` 打 `/models`，
 *    其余用 Bearer）；留空 = 用已登记条目的格式，再缺省 openai
 *  - **v1.45：以下四项一律「请求体优先 → 已登记条目」**——前端卡片的「拉取模型」用**草稿**值探测，
 *    而草稿里的条目后端还没保存（旧实现只发名字 → 新条目一律报「未填模型地址（base_url）」，
 *    自定义格式还会因缺额外请求头而 401） */
export interface ProviderModelsRequest {
  provider?: string;
  base_url?: string;
  api_key?: string;
  format?: ProviderFormat;
  /** v1.45：自定义请求路径（仅 custom 有意义；留空 = 用已登记条目，再缺省 /chat/completions） */
  api_path?: string;
  /** v1.45：额外 HTTP 请求头（各格式通用；留空 = 用已登记条目） */
  extra_headers?: Record<string, string>;
}

/** 模型探测响应：失败不抛异常，服务端/网络错误原文放 `error`（界面必须看得见） */
export interface ProviderModelsResponse {
  models: string[];
  error: string;
  elapsed_ms: number;
}

/** 配置更新请求 (PUT /settings) 只下发需要修改的字段即可。
 *  密钥幂等语义：providers[*].api_key 提交掩码值或空串 = 保留现值。
 *  v1.33：**掩码形状的值（`xxx****xxxx` / `****`）一律不落库**——现值为空时也不写入，
 *  新条目（重命名/复制 provider）带来的掩码视为「未填」，绝不当真钥写盘。
 *  v1.34：**删除 llm_* 主配置字段**（AI 身份只在 providers 里；`primary` 特殊分支已移除）。
 *  v1.35：① 提交已移除的 llm_* 字段 → **422 明确报错**（此前静默忽略，旧界面会显示「已保存」
 *  而实际什么都没改）；② `providers[*].clear_api_key: true` = 显式清空密钥。
 *  v1.36：**前端可配置面补齐**——检索 / 健康 / 维护 / 日志 / WAL 各项均可改并落盘；
 *  被环境变量顶掉的项**不写入内存**，响应 `ignored_by_env` 点名是哪个变量（不再静默无效）。
 *  值域越界返回 422（agent_mode / log_level 枚举 + 数值范围，见 protocol.md v1.13） */
export interface SettingsUpdateRequest {
  memory_db_path?: string;       // v1.16：持久化 dpim.json，重启生效（数据文件不自动迁移）
  graph_json_path?: string;      // v1.16：同上
  providers?: Record<string, ProviderEntry>;
  active_provider?: string;
  active_model?: string;
  agent_mode?: AgentMode;
  agent_max_retries?: number;
  agent_cr_model?: string;
  agent_in_model?: string;
  agent_gr_model?: string;
  agent_meta_model?: string;
  llm_structured_mode?: 'md_json' | 'json' | 'tools';
  max_graph_hops?: number;
  rrf_k?: number;
  jaccard_threshold?: number;
  max_raw_content?: number;        // v1.36：1000..10000000
  health_check_interval?: number;
  /** v1.32：健康检查超时（秒，10..3600）；此前 TS 侧缺失，前端只能本地扩展类型硬接 */
  health_check_timeout?: number | null;
  compensate_batch_size?: number;
  compensate_check_interval?: number;   // v1.36：1..3600
  agent_maintain_auto?: boolean;
  agent_maintain_min_nodes?: number;
  agent_maintain_max_nodes?: number;
  agent_maintain_cooldown?: number;
  agent_cmdmsg_max_rounds?: number;     // v1.36：1..10
  agent_cr_skip_chars?: number;         // v1.36：0..100000
  log_level?: string;
  log_retention_days?: number;          // v1.36：0..3650（0 = 不清理）
  log_jsonl?: boolean;
  agent_logs_full?: boolean;
  wal_checkpoint_interval?: number;     // v1.36：10..86400
  wal_checkpoint_bytes?: number;        // v1.36：1MiB..1GiB
  graph_ops_retention?: number;         // v1.39：0..1000000（0 = 不压实）
  trash_retention_days?: number;        // v1.39：0..3650（0 = 永不清理）
}

/** 手动图维护请求体 (POST /agent/maintain，v1.32)
 *  mode='update'（默认）= 两阶段结构优化（Phase1 减碎+补缺 → Phase2 连线）；
 *  mode='compress' = 删繁就简（压缩 data 节点/合并/删僵尸）。body 可省略（缺省 update）。
 *  修复前该端点完全不读 body → payload 恒为 {} → 选 update 实际走 compress。 */
export interface MaintainRequest {
  mode?: 'compress' | 'update';
}

// ==================== 配置项（类型参考）====================
export interface DPIMConfig {
  MEMORY_DB_PATH: string;
  GRAPH_JSON_PATH: string;
  // v1.34：DPIM_LLM_* 不再有内置默认（旧默认是 ollama + llama3:8b，已删除）。
  // 显式给出 LLM_BASE_URL 且注册表为空时，才合成一条名为 `default` 的提供商条目。
  LLM_BASE_URL: string;
  LLM_API_KEY: string;
  LLM_MODEL_NAME: string;
  LLM_TIMEOUT: number;            // 全局调优默认（provider 条目可覆盖）
  LLM_MAX_TOKENS?: number;        // 输出 token 上限（0/空 = 服务端默认）
  LLM_ENABLE_THINKING?: boolean;  // 思考开关（空 = 服务端默认）
  LLM_THINKING_BUDGET?: number;   // 思考预算 tokens（0/空 = 不设）
  // BYOK 多模型网关
  PROVIDERS?: string;             // JSON dict：{name: {base_url, api_key, model, timeout, max_tokens, enable_thinking, thinking_budget, thinking_style, extra_body, structured_mode}}
  ACTIVE_PROVIDER: string;      // 默认空（注册表首个自动成为活动提供商）
  // Agent 管线
  AGENT_MODE: AgentMode;        // 默认 'disabled'
  AGENT_MAX_RETRIES: number;    // 默认 2
  MAX_RAW_CONTENT: number;      // 上下文护栏：单次 LLM 输入中 raw_content 最大字符数（默认 200000）
  AGENT_CR_MODEL: string;
  AGENT_IN_MODEL: string;
  AGENT_GR_MODEL: string;
  AGENT_META_MODEL: string;
  MAX_GRAPH_HOPS: number;
  RRF_K: number;
  JACCARD_THRESHOLD: number;
  HEALTH_CHECK_INTERVAL: number;
  HEALTH_CHECK_TIMEOUT: number;   // 健康检查超时（秒，默认 60，与生成超时分离）
  COMPENSATE_BATCH_SIZE: number;
  COMPENSATE_CHECK_INTERVAL: number;  // 补偿批次结果检查间隔（秒，默认 5）
  AGENT_MAINTAIN_AUTO: boolean;      // 图维护自动触发：AI 恢复时顺带整理图谱（默认 true）
  AGENT_MAINTAIN_MIN_NODES: number;  // 自动维护最小图规模（节点数，默认 10；手动触发不受限）
  AGENT_MAINTAIN_MAX_NODES: number;  // 节点规模高水位（v1.20：默认 200，达到后每冷却周期都准备压缩，并放宽合并）
  AGENT_MAINTAIN_COOLDOWN: number;   // 高水位自动维护冷却（秒，v1.20：默认 60）
  LOG_LEVEL: string;
  // v1.30：本地日志（前后端分文件，按天轮转；仅 env，不经 API 下发）
  LOG_DIR: string;                  // 默认 <dpim>/logs
  LOG_RETENTION_DAYS: number;       // 默认 14（0 = 不清理）
  LOG_JSONL: boolean;               // 默认 false
  // v1.30：WAL 治理
  WAL_CHECKPOINT_INTERVAL: number;  // 默认 300 秒
  WAL_CHECKPOINT_BYTES: number;     // 默认 8 MiB
}

// ==================== 存储维护（v1.30）====================

/** POST /maintenance/backup */
export interface BackupResponse {
  status: 'ok';
  backup_dir: string;
  stamp: string;
  pruned: number;
  manifest: Record<string, unknown>;
}

/** GET /maintenance/backups */
export interface BackupListResponse {
  backups: Array<{
    stamp: string;
    path: string;
    bytes: number;
    manifest: Record<string, unknown>;
  }>;
}

export interface VerifyCheck {
  name: string;
  ok: boolean;
  detail: string;
}

/** POST /maintenance/verify */
export interface VerifyResponse {
  ok: boolean;
  checks: VerifyCheck[];
  sizes: Record<string, unknown>;
  counts: Record<string, unknown>;
}

/** GET /maintenance/ops */
export interface GraphOpItem {
  op_id: number;
  created_at: string;
  op_kind: 'node_upsert' | 'node_delete' | 'edge_upsert' | 'edge_delete' | 'graph_clear';
  reason: string;   // 因何改了图（维护计划/指令等）
  actor: string;
  payload: Record<string, unknown>;
}

export interface GraphOpListResponse {
  ops: GraphOpItem[];
  total: number;
}

/** POST /maintenance/checkpoint */
export interface CheckpointResponse {
  status: 'ok';
  busy: number;
  log_frames: number;
  checkpointed_frames: number;
  wal_bytes: number;
}

/** POST /repos/{repo_id}/refresh */
export interface RepoRefreshResponse {
  status: 'ok';
  repo_id: string;
  name: string;
  events: number;
  nodes: number;
  edges: number;
  reconcile_changed: number;
  last_reconcile_at: string;
  message: string;
}

// ==================== 本地日志（v1.31）====================

/** GET /logs 的文件项（按天轮转的一份日志） */
export interface LogFileInfo {
  name: string;
  kind: 'backend' | 'frontend';
  date: string;            // YYYY-MM-DD
  size: number;
  mtime: number;           // 文件修改时间（epoch 秒）
}

/** GET /logs —— kind/date/level/keyword/tail；只读，不触发状态密钥刷新 */
export interface LogsResponse {
  kind: 'backend' | 'frontend';
  date: string;            // 实际返回的日期（date 未给 = 该通道最新日期）
  dir: string;             // 日志目录绝对路径
  files: LogFileInfo[];    // 该通道全部可用日志（日期倒序）
  lines: string[];         // 过滤后的尾部若干行
  truncated: boolean;      // 过滤后匹配行数超过 tail
}

/** POST /logs/client —— message 超 8000 字符截断；落 frontend-YYYY-MM-DD.log
 *  注意：日志上报属旁路，**不刷新状态校验密钥**（write_commit 按路径+方法精确豁免） */
export interface ClientLogRequest {
  level: 'debug' | 'info' | 'warning' | 'error';
  message: string;
  source?: string;
}

export interface ClientLogResponse {
  ok: true;
}

// ==================== 回收站（v1.31）====================

/** GET /trash 的留档条目 */
export interface TrashItem {
  kind: 'event' | 'node' | 'graph';   // graph = 整图留档（v1.42，DELETE /graph 清空前自动留档）
  id: string;
  archived_at: string;
  size: number;
  title: string;           // 留档内容里的标题/内容摘要（整图留档为「整图留档：N 节点 / M 边」）
  path: string;
}

export interface TrashListResponse {
  items: TrashItem[];
  dir: string;
}

/** POST /trash/restore —— 事件/节点：已存在同 id → 409；找不到留档 → 404。
 *  整图（v1.42）：**合并式**补回（已存在的节点/边跳过、不覆盖、不报 409）。 */
export interface TrashRestoreRequest {
  kind: 'event' | 'node' | 'graph';
  id: string;
}

export interface TrashRestoreResponse {
  message: string;
}

// ==================== 库登记恢复与清除（v1.31）====================

/** POST /repos/rebuild —— 坏索引恢复；绝不删除任何磁盘数据文件 */
export interface RepoRebuildResponse {
  message: string;
  repos: number;
  latched_before: boolean;  // 重建前登记表是否处于「坏索引只读锁存」态
}

/** POST /repos/{repo_id}/purge —— 先备份再删文件；外部库只摘登记 */
export interface RepoPurgeResponse {
  message: string;
  backup_path: string;      // 清除前的强制备份目录（外部库/无法备份时为空串）
}
