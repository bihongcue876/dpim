/** 知识图谱：节点与边（图层 / 衍生）（api 域：nodes） */
import { qs, req } from './http'
import type {
  ClearGraphResponse,
  EdgeListResponse,
  NodeDetail,
  NodeListItem,
  PaginatedResponse,
} from './types'

export interface ListNodesParams {
  type?: string
  query?: string
  limit?: number
  offset?: number
  repo_id?: string
  repo_ids?: string[]
}

export interface ListEdgesParams {
  /** 两侧命中：出边 + 入边（与节点详情的 edges 同口径） */
  node_id?: string
  source?: string
  target?: string
  relation?: string
  limit?: number
  offset?: number
  repo_id?: string
  repo_ids?: string[]
}

export function listNodes(p: ListNodesParams): Promise<PaginatedResponse<NodeListItem>> {
  return req<PaginatedResponse<NodeListItem>>(
    `/nodes${qs({
      type: p.type,
      query: p.query,
      limit: p.limit,
      offset: p.offset,
      repo_id: p.repo_id,
      repo_ids: p.repo_ids,
    })}`,
  )
}

/**
 * 边列表（v1.37 `GET /edges`）。
 *
 * 图谱页一次取全：此前只能逐节点 `getNode` 汇总边（400 节点 ≈ 17 批请求），
 * 且任一批失败即静默丢边。`limit` 后端限定 0..5000，越界 400。
 */
export function listEdges(p: ListEdgesParams = {}): Promise<EdgeListResponse> {
  return req<EdgeListResponse>(
    `/edges${qs({
      node_id: p.node_id,
      source: p.source,
      target: p.target,
      relation: p.relation,
      limit: p.limit,
      offset: p.offset,
      repo_id: p.repo_id,
      repo_ids: p.repo_ids,
    })}`,
  )
}

export function getNode(nodeId: string, repoId?: string): Promise<NodeDetail> {
  return req<NodeDetail>(`/nodes/${nodeId}${qs({ repo_id: repoId })}`)
}

/** 人工建节点（衍生知识：可由 AI 维护，也可人工补） */
export function createNode(
  title: string,
  content = '',
  sourceEventId = '',
): Promise<{ node_id: string }> {
  return req('/nodes', {
    method: 'POST',
    body: JSON.stringify({ title, content, source_event_id: sourceEventId }),
  })
}

/** 修订节点内容（system 节点被后端拒绝：人工维护语义） */
export function putNode(nodeId: string, content: string): Promise<{ message: string }> {
  return req(`/nodes/${nodeId}`, { method: 'PUT', body: JSON.stringify({ content }) })
}

/** 追加源事件（幂等） */
export function addNodeSourceRef(nodeId: string, eventId: string): Promise<{ message: string }> {
  return req(`/nodes/${nodeId}`, {
    method: 'PUT',
    body: JSON.stringify({ add_source_event_id: eventId }),
  })
}

/** 移除源事件（后端守卫：最少保留 1 条有效源证，否则 409） */
export function removeNodeSourceRef(
  nodeId: string,
  eventId: string,
): Promise<{ message: string }> {
  return req(`/nodes/${nodeId}`, {
    method: 'PUT',
    body: JSON.stringify({ remove_source_event_id: eventId }),
  })
}

export function deleteNode(nodeId: string, force = false): Promise<{ message: string }> {
  return req(`/nodes/${nodeId}`, {
    method: 'DELETE',
    body: JSON.stringify({ force }),
  })
}

export function createEdge(
  source: string,
  target: string,
  relation: string,
  evidenceEventId = '',
): Promise<{ message: string }> {
  return req('/edges', {
    method: 'POST',
    body: JSON.stringify({ source, target, relation, evidence_event_id: evidenceEventId }),
  })
}

export function deleteEdge(source: string, target: string): Promise<{ message: string }> {
  return req(`/edges${qs({ source, target })}`, { method: 'DELETE' })
}

/** DELETE /graph —— 清空活动书目图层（v1.42：先留档整图 + 撤销线层派生链接）。
 *
 *  用**契约类型**而不是就地声明：这里原来自写了一份 7 字段类型（因为契约的
 *  `ClearGraphResponse` 当时只有 status/message）——就地声明等于把「类型在骗人」的引信留着，
 *  契约补齐（v1.46）后改为直接引用。 */
export function clearGraph(): Promise<ClearGraphResponse> {
  return req('/graph', { method: 'DELETE' })
}
