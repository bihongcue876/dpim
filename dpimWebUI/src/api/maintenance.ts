/** 存储保障：备份 / 一致性校验 / 图层操作日志 / WAL（api 域：maintenance） */
import { qs, req } from './http'
import type {
  BackupListResponse,
  BackupResponse,
  CheckpointResponse,
  GraphOpListResponse,
  VerifyResponse,
} from './types'

/** 整库备份（SQLite 在线副本 + graph.json + 清单） */
export function createBackup(note = '', repoId?: string): Promise<BackupResponse> {
  return req<BackupResponse>(`/maintenance/backup${qs({ note, repo_id: repoId })}`, {
    method: 'POST',
  })
}

export function listBackups(repoId?: string): Promise<BackupListResponse> {
  return req<BackupListResponse>(`/maintenance/backups${qs({ repo_id: repoId })}`)
}

/** 只读一致性校验（含操作日志重放一致性） */
export function verify(repoId?: string): Promise<VerifyResponse> {
  return req<VerifyResponse>(`/maintenance/verify${qs({ repo_id: repoId })}`, {
    method: 'POST',
  })
}

/** 图层操作日志（审计：谁/何时/因何改了图） */
export function listOps(params: {
  repo_id?: string
  limit?: number
  offset?: number
}): Promise<GraphOpListResponse> {
  return req<GraphOpListResponse>(
    `/maintenance/ops${qs({
      repo_id: params.repo_id,
      limit: params.limit,
      offset: params.offset,
    })}`,
  )
}

/** WAL 检查点（TRUNCATE） */
export function checkpoint(repoId?: string): Promise<CheckpointResponse> {
  return req<CheckpointResponse>(`/maintenance/checkpoint${qs({ repo_id: repoId })}`, {
    method: 'POST',
  })
}
