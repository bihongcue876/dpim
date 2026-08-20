function base(): string {
  return localStorage.getItem('dpim_backend_url') || ''
}

/** 后端启用 DPIM_API_KEY 时随请求附带认证头（本地默认无认证，头为空不发送） */
function authHeaders(): Record<string, string> {
  const key = localStorage.getItem('dpim_api_key') || ''
  return key ? { 'X-API-Key': key } : {}
}

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  // FastAPI 422 校验错误的 detail 是数组 [{loc,msg,type},...]
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => {
        // loc 形如 ['body','llm_timeout']，过滤 'body' 后取字段路径，让报错可定位到具体字段
        const loc = Array.isArray(d?.loc)
          ? (d.loc as unknown[]).filter(x => typeof x === 'string').join('.')
          : ''
        const msg = d && typeof d.msg === 'string' ? d.msg : String(d)
        return loc ? `${loc}: ${msg}` : msg
      })
      .join('; ')
  }
  if (detail && typeof detail === 'object') {
    try { return JSON.stringify(detail) } catch { return String(detail) }
  }
  return String(detail)
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(base() + url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...init?.headers,
    },
  })
  if (!res.ok) {
    // FastAPI 错误信封为 {detail: "..."}，兼容 {message} / {error:{message}} 两种；
    // detail 可能是数组（422 校验错误），序列化为可读文本避免 "[object Object]"
    let detail: unknown = res.statusText
    try {
      const body = await res.json()
      detail = body?.detail ?? body?.message ?? body?.error?.message ?? res.statusText
    } catch { /* 非 JSON 响应，使用 statusText */ }
    throw new Error(formatErrorDetail(detail))
  }
  return res.json()
}

// ── Types (mirrors share/protocol.ts) ──

export interface StateHashResponse {
  hash: string
  changed_at: string
}

export interface EventListItem {
  event_id: string
  created_at: string
  raw_content: string
  event_type: string
  status: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface NodeListItem {
  node_id: string
  title: string
  node_type: string
  confidence: number
}

export interface EdgeInfo {
  source: string
  target: string
  relation: string
  evidence_event_id: string
}

export interface NodeDetail {
  node_id: string
  title: string
  content: string
  node_type: string
  source_refs: Array<{ event_id: string; valid: boolean; hash: string }>
  confidence: number
  metadata: Record<string, unknown>
  edges: EdgeInfo[]
}

export interface SearchResult {
  node_id: string
  title: string
  snippet: string
  score: number
  source_events: string[]
  source_type: string
  confidence: number
  degraded: boolean
}

export interface HealthResponse {
  status: string
  ai_available: boolean
  layers: { event_line: Record<string, number>; knowledge_graph: Record<string, number> }
  last_event_at: string
  version: string
}

export interface SettingsResponse {
  memory_db_path: string
  graph_json_path: string
  llm_base_url: string
  llm_api_key: string
  llm_model_name: string
  llm_timeout: number
  llm_max_tokens: number | null
  llm_enable_thinking: boolean | null
  llm_thinking_budget: number | null
  available_providers: string[]
  providers: Record<string, { base_url: string; api_key: string; model?: string; models?: string[]; timeout?: number }>
  active_provider: string
  available_models: string[]
  active_model: string
  agent_mode: string
  agent_max_retries: number
  agent_cr_model: string
  agent_in_model: string
  agent_gr_model: string
  agent_meta_model: string
  max_graph_hops: number
  rrf_k: number
  jaccard_threshold: number
  health_check_interval: number
  health_check_timeout: number
  compensate_batch_size: number
  log_level: string
}

// ── API functions ──

export async function getStateHash(): Promise<StateHashResponse> {
  return req('/state-hash')
}

export async function getHealth(): Promise<HealthResponse> {
  return req('/health')
}

export interface LLMCallLog {
  role: string
  timestamp: number
  model: string
  input_preview: string
  input?: string
  output: string
  error: string
}

export async function getAgentLogs(limit = 30, full = false): Promise<{ logs: LLMCallLog[] }> {
  return req(`/agent/logs?limit=${limit}${full ? '&full=true' : ''}`)
}

/** 手动触发补偿：把 raw/indexed 积压事件重新入队走 Agent 管线 */
export async function compensate(): Promise<{ message?: string }> {
  return req('/agent/compensate', { method: 'POST' })
}

export async function listEvents(params: {
  status?: string
  type?: string
  limit?: number
  offset?: number
}): Promise<PaginatedResponse<EventListItem>> {
  const q = new URLSearchParams()
  if (params.status) q.set('status', params.status)
  if (params.type) q.set('type', params.type)
  if (params.limit) q.set('limit', String(params.limit))
  if (params.offset) q.set('offset', String(params.offset))
  return req(`/events?${q}`)
}

export async function getEvent(eventId: string): Promise<Record<string, unknown>> {
  return req(`/events/${eventId}`)
}

export async function deleteEvent(eventId: string): Promise<void> {
  await req(`/events/${eventId}`, { method: 'DELETE' })
}

export async function putEventStatus(eventId: string, status: string): Promise<void> {
  await req(`/events/${eventId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  })
}

export async function putEvent(eventId: string, content: string): Promise<void> {
  await req(`/events/${eventId}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

export async function createEdge(source: string, target: string, relation: string, evidenceEventId = ''): Promise<void> {
  await req('/edges', {
    method: 'POST',
    body: JSON.stringify({ source, target, relation, evidence_event_id: evidenceEventId }),
  })
}

export async function deleteEdge(source: string, target: string): Promise<void> {
  await req(`/edges?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}`, {
    method: 'DELETE',
  })
}

export async function createNode(title: string, content = '', sourceEventId = ''): Promise<{ node_id: string }> {
  return req('/nodes', {
    method: 'POST',
    body: JSON.stringify({ title, content, source_event_id: sourceEventId }),
  })
}

export async function clearGraph(): Promise<void> {
  await req('/graph', { method: 'DELETE' })
}

export async function listNodes(params: {
  type?: string
  limit?: number
  offset?: number
}): Promise<PaginatedResponse<NodeListItem>> {
  const q = new URLSearchParams()
  if (params.type) q.set('type', params.type)
  if (params.limit) q.set('limit', String(params.limit))
  if (params.offset) q.set('offset', String(params.offset))
  return req(`/nodes?${q}`)
}

export async function getNode(nodeId: string): Promise<NodeDetail> {
  return req(`/nodes/${nodeId}`)
}

export async function putNode(nodeId: string, content: string): Promise<void> {
  await req(`/nodes/${nodeId}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}

export async function deleteNode(nodeId: string, force = false): Promise<void> {
  await req(`/nodes/${nodeId}`, {
    method: 'DELETE',
    body: JSON.stringify({ force }),
  })
}

export async function ingest(content: string, eventType = 'auto'): Promise<{ event_id: string; status: string }> {
  return req('/ingest', {
    method: 'POST',
    body: JSON.stringify({ content, event_type: eventType }),
  })
}

export async function query(params: {
  query: string
  source_filter?: string
  max_hops?: number
  limit?: number
  offset?: number
}): Promise<{ results: SearchResult[]; total: number; degraded: boolean }> {
  return req('/query', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export async function postFeedback(resultId: string, accepted: boolean): Promise<void> {
  await req('/feedback', {
    method: 'POST',
    body: JSON.stringify({ result_id: resultId, accepted }),
  })
}

export async function getSettings(): Promise<SettingsResponse> {
  return req('/settings')
}

export async function putSettings(body: {
  llm_base_url?: string
  llm_api_key?: string
  llm_model_name?: string
  llm_timeout?: number
  llm_max_tokens?: number | null
  llm_enable_thinking?: boolean | null
  llm_thinking_budget?: number | null
  providers?: Record<string, unknown>
  active_provider?: string
  active_model?: string
  agent_mode?: string
  agent_max_retries?: number
  agent_cr_model?: string
  agent_in_model?: string
  agent_gr_model?: string
  agent_meta_model?: string
  max_graph_hops?: number
  rrf_k?: number
  jaccard_threshold?: number
  health_check_interval?: number
  health_check_timeout?: number
  compensate_batch_size?: number
  log_level?: string
}): Promise<void> {
  await req('/settings', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}
