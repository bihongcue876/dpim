/** 运行配置（api 域：settings） */
import { req } from './http'
import type {
  ProviderModelsRequest,
  ProviderModelsResponse,
  SettingsResponse,
  SettingsUpdateRequest,
} from './types'

export function getSettings(): Promise<SettingsResponse> {
  return req<SettingsResponse>('/settings')
}

/**
 * `PUT /settings` 的响应体（v1.36）。
 *
 * 契约 `share/protocol.ts` 目前只收录了**请求**类型 `SettingsUpdateRequest`（响应类型缺失），
 * 因此这里按后端实际返回的字段就地收窄；契约补齐后本接口删除、改从 `@protocol` 导入
 * （与 `api/types.ts` 里 `EventDetailResponse` 的做法一致）。
 *
 * `ignored_by_env` 非空 = 这些字段被环境变量顶掉、**本次未写入**，条目形如 `"rrf_k(DPIM_RRF_K)"`。
 */
export interface SettingsUpdateResult {
  status?: string
  message?: string
  ignored_by_env?: string[]
}

export function putSettings(body: SettingsUpdateRequest): Promise<SettingsUpdateResult> {
  return req<SettingsUpdateResult>('/settings', { method: 'PUT', body: JSON.stringify(body) })
}

/** 探测提供商的可用模型列表（v1.34）：失败原因在 `error` 里，不抛异常 */
export function probeProviderModels(body: ProviderModelsRequest): Promise<ProviderModelsResponse> {
  return req<ProviderModelsResponse>('/settings/models', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
