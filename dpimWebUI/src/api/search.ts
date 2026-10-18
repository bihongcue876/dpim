/** 检索与反馈（api 域：search） */
import { req } from './http'
import type { FeedbackResponse, SearchRequest, SearchResponse } from './types'

/**
 * 综合检索（联查）：`repo_ids` 由调用方决定——顶栏勾 1 本传单元素列表（= 指定库检索），
 * 勾 ≥2 本传子集（= 联合检索：逐库候选池 → RRF 融合）；不传则后端按活动书目。
 */
export function query(body: SearchRequest): Promise<SearchResponse> {
  return req<SearchResponse>('/query', { method: 'POST', body: JSON.stringify(body) })
}

/** 反馈：跨库结果必须带 repo_id，否则静默落在活动库 */
export function postFeedback(
  resultId: string,
  accepted: boolean,
  repoId?: string,
): Promise<FeedbackResponse> {
  return req<FeedbackResponse>('/feedback', {
    method: 'POST',
    body: JSON.stringify({ result_id: resultId, accepted, repo_id: repoId ?? '' }),
  })
}
