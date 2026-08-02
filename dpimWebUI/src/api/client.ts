function base(): string {
  return localStorage.getItem('dpim_backend_url') || ''
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(base() + url, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: { code: 'UNKNOWN', message: res.statusText } }))
    throw new Error(body.error?.message ?? res.statusText)
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
  available_providers: string[]
  active_provider: string
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

export async function putSettings(body: Partial<SettingsResponse>): Promise<void> {
  await req('/settings', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}
