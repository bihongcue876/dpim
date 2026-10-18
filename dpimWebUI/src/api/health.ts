/** 健康 / 状态密钥 / AI 日志 / 管线动作（api 域：health） */
import { qs, req } from './http'
import type {
  AgentLogsResponse,
  CompensateResponse,
  HealthResponse,
  StateHashResponse,
} from './types'

export function getHealth(repoId?: string): Promise<HealthResponse> {
  return req<HealthResponse>(`/health${qs({ repo_id: repoId })}`)
}

export function getStateHash(): Promise<StateHashResponse> {
  return req<StateHashResponse>('/state-hash')
}

export function getAgentLogs(limit = 30, full = false): Promise<AgentLogsResponse> {
  return req<AgentLogsResponse>(`/agent/logs${qs({ limit, full: full ? 'true' : '' })}`)
}

/** 手动补偿：把 raw/indexed 积压事件重新入队走 Agent 管线 */
export function compensate(repoId?: string): Promise<CompensateResponse> {
  return req<CompensateResponse>(`/agent/compensate${qs({ repo_id: repoId })}`, {
    method: 'POST',
  })
}

/** 手动触发图维护（合并/压缩/补边/指令） */
export function maintain(mode = 'update', repoId?: string): Promise<{ message?: string }> {
  return req(`/agent/maintain${qs({ repo_id: repoId })}`, {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })
}
