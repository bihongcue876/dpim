/**
 * 跨书目写入（composable）：写操作必须落到「活动书目」。
 *
 * 后端语义：`PUT/DELETE /events/*`、`PUT/DELETE /nodes/*` 只作用于**活动书目**
 * （只有详情读取与反馈接受 `repo_id`）。因此从联查列表里点开某本书目的条目后
 * 要修订它，必须先把那本书目设为活动书目。
 *
 * 本 composable 把这件事**显式化**：页面先问 `needsActivation()`，
 * 需要时弹二次确认说明影响，用户确认后再 `activate()` 并继续写。
 * 不做静默切换（P1 可见性 / P6 失败可见）。
 */
import { computed } from 'vue'
import { useRepoStore } from '@/stores/repo'

export function useRepoWrite() {
  const repo = useRepoStore()

  const activeRepoId = computed(() => repo.activeRepoId)
  const activeRepoName = computed(() => repo.activeRepo?.name ?? '—')

  /** 目标条目不属活动书目 → 写入前需要切换 */
  function needsActivation(targetRepoId?: string): boolean {
    if (!targetRepoId) return false
    return targetRepoId !== repo.activeRepoId
  }

  function nameOf(repoId?: string): string {
    return repo.nameOf(repoId)
  }

  /** 切换活动书目；失败原样抛出，由页面展示 */
  async function activate(repoId: string): Promise<void> {
    await repo.activate(repoId)
  }

  /** 二次确认对话框的影响说明（含目标书目名） */
  function activationImpacts(targetRepoId: string): string[] {
    return [
      `目标条目属于书目《${nameOf(targetRepoId)}》，当前活动书目是《${activeRepoName.value}》。`,
      'DPIM 的写操作只作用于活动书目，继续将把活动书目切换过去。',
      '切换只影响「当前活动书目」，不改动任何数据。',
    ]
  }

  return { activeRepoId, activeRepoName, needsActivation, nameOf, activate, activationImpacts }
}
