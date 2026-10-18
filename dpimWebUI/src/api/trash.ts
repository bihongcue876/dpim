/** 回收站（api 域：trash）——物理删除前的留档与恢复 */
import { qs, req } from './http'
import type { TrashListResponse } from './types'

export function listTrash(repoId?: string): Promise<TrashListResponse> {
  return req<TrashListResponse>(`/trash${qs({ repo_id: repoId })}`)
}

/** 按原 id 恢复留档的事件/节点；kind='graph' 时按整图**合并式**补回（v1.42） */
export function restoreTrash(
  kind: 'event' | 'node' | 'graph',
  id: string,
  repoId?: string,
): Promise<{ message: string }> {
  return req(`/trash/restore${qs({ repo_id: repoId })}`, {
    method: 'POST',
    body: JSON.stringify({ kind, id }),
  })
}
