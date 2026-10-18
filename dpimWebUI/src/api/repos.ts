/** 书目（库）与分组（api 域：repos） */
import { qs, req } from './http'
import type {
  RepoAdoptResponse,
  RepoCreateRequest,
  RepoInfo,
  RepoListResponse,
  RepoPurgeResponse,
  RepoRebuildResponse,
  RepoRefreshResponse,
} from './types'

export function listRepos(): Promise<RepoListResponse> {
  return req<RepoListResponse>('/repos')
}

export function getRepo(repoId: string): Promise<RepoInfo> {
  return req<RepoInfo>(`/repos/${repoId}`)
}

export function createRepo(body: RepoCreateRequest): Promise<{ repo_id: string; message: string }> {
  return req('/repos', { method: 'POST', body: JSON.stringify(body) })
}

/** 元数据修订；`root` 仅对外部书目有效（重指向） */
export function updateRepo(
  repoId: string,
  body: {
    name?: string
    note?: string
    group?: string
    managed?: boolean
    root?: string
  },
): Promise<{ message: string }> {
  return req(`/repos/${repoId}`, { method: 'PUT', body: JSON.stringify(body) })
}

/** 摘除登记（不删磁盘文件；默认库/活动库由后端拒绝） */
export function deleteRepo(repoId: string): Promise<{ message: string }> {
  return req(`/repos/${repoId}`, { method: 'DELETE' })
}

export function activateRepo(repoId: string): Promise<{ message: string }> {
  return req(`/repos/${repoId}/activate`, { method: 'POST' })
}

/** 刷新/修复：重载该库（坏文件走留档，不静默覆盖） */
export function refreshRepo(repoId: string): Promise<RepoRefreshResponse> {
  return req<RepoRefreshResponse>(`/repos/${repoId}/refresh`, { method: 'POST' })
}

/** 联合生成知识：把该库积压事件入队走管线 */
export function generateRepo(repoId: string): Promise<{ message: string; queued?: number }> {
  return req(`/repos/${repoId}/generate`, { method: 'POST' })
}

/** 重建登记表（坏 repos/index.json 的出路） */
export function rebuildRepos(): Promise<RepoRebuildResponse> {
  return req<RepoRebuildResponse>('/repos/rebuild', { method: 'POST' })
}

/**
 * 收养目录（v1.32）：目录里只有 memory.db 或只有 graph.json 时，补出缺失的空件并登记为外部书目。
 * **只补空件，绝不覆盖已存在文件**；补 graph.json 时后端会顺带尝试从 `graph_ops` 重放恢复图层。
 * `created` = 实际补出来的文件名（两个都在则为空数组）。
 */
export function adoptRepo(
  root: string,
  name: string,
  note = '',
  group = '',
  adoptMissing = true,
): Promise<RepoAdoptResponse> {
  return req<RepoAdoptResponse>('/repos/adopt', {
    method: 'POST',
    body: JSON.stringify({
      root,
      name,
      note,
      group,
      adopt_missing: adoptMissing,
    }),
  })
}

/** 删除书目及其磁盘文件（先备份；外部库只摘除登记） */
export function purgeRepo(repoId: string): Promise<RepoPurgeResponse> {
  return req<RepoPurgeResponse>(`/repos/${repoId}/purge`, { method: 'POST' })
}

/** 受管且已加载（可被检索/写入）的书目 */
export function selectableRepos(repos: RepoInfo[]): RepoInfo[] {
  return repos.filter((r) => r.managed && r.loaded)
}

export { qs }
