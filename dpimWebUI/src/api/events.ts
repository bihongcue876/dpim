/** 时序事件存储（线层 / 原文）（api 域：events） */
import { qs, req } from './http'
import type {
  EventDetailResponse,
  EventListItem,
  IngestResponse,
  PaginatedResponse,
} from './types'

export interface ListEventsParams {
  status?: string
  type?: string
  query?: string
  limit?: number
  offset?: number
  /** 单库（缺省 = 活动库） */
  repo_id?: string
  /** 联查：多库（逗号分隔） */
  repo_ids?: string[]
}

export function listEvents(p: ListEventsParams): Promise<PaginatedResponse<EventListItem>> {
  return req<PaginatedResponse<EventListItem>>(
    `/events${qs({
      status: p.status,
      type: p.type,
      query: p.query,
      limit: p.limit,
      offset: p.offset,
      repo_id: p.repo_id,
      repo_ids: p.repo_ids,
    })}`,
  )
}

/** 详情：跨库跳转必须带 repo_id，否则只在活动库里找（静默 404） */
export function getEvent(eventId: string, repoId?: string): Promise<EventDetailResponse> {
  return req<EventDetailResponse>(`/events/${eventId}${qs({ repo_id: repoId })}`)
}

/** 修订原文：**仅人类通道**（无 AI 入口） */
export function putEvent(
  eventId: string,
  body: { content?: string; event_type?: string },
): Promise<{ message: string }> {
  return req(`/events/${eventId}`, { method: 'PUT', body: JSON.stringify(body) })
}

/** 状态修订（转 indexed 时后端会视情况重新入队走管线） */
export function putEventStatus(eventId: string, status: string): Promise<{ message: string }> {
  return req(`/events/${eventId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  })
}

export function deleteEvent(eventId: string): Promise<{ message: string }> {
  return req(`/events/${eventId}`, { method: 'DELETE' })
}

/** 写入原文（信息传入页）：纯存储；指令经同一入口分发 */
export function ingest(
  content: string,
  eventType: string,
  repoId = '',
): Promise<IngestResponse> {
  return req<IngestResponse>('/ingest', {
    method: 'POST',
    body: JSON.stringify({ content, event_type: eventType, repo_id: repoId }),
  })
}
