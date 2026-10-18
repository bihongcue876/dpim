/**
 * 书目作用域（composable）：页面按「顶栏勾选的书目集合」取数时的唯一入口。
 *
 * 作用域不是「单库 / 全部」两态，而是**用户自己勾选的库子集**：
 *   - 勾 1 个 → 单库：`repo_id`（写动作也打它）
 *   - 勾 ≥2 个 → 子集联查：`repo_ids`（后端逐库取候选池后融合，分页只切一次）
 *
 * 因此页面**不要**再各写 `isJoint ? '' : effectiveRepoId` 这种散写法，
 * 一律用 `repoParams()` 取参数、用 `scopeKey` 当 watch 依赖、用 `scopeLabel` 显示「具体是哪几个库」。
 */
import { computed } from 'vue'
import { useRepoStore } from '@/stores/repo'
import type { RepoScopeParams } from '@/stores/repo'

/** 中文数量词（联查文案用）：2 → 「两」 */
const CN_NUM: Record<number, string> = {
  2: '两',
  3: '三',
  4: '四',
  5: '五',
  6: '六',
  7: '七',
  8: '八',
  9: '九',
  10: '十',
}

export function useRepoScope() {
  const repo = useRepoStore()

  /** 勾选集合（顺序稳定：按登记表顺序） */
  const selectedIds = computed(() => repo.selectedIds)
  const selectedRepos = computed(() => repo.selectedRepos)
  /** 勾选的书目名（联查文案要说出**具体是哪几个库**） */
  const selectedNames = computed(() => repo.selectedRepos.map((r) => r.name))

  /** 恰好 1 个 → 该库 id；否则空串（写动作与单库读请求的目标） */
  const effectiveRepoId = computed(() => repo.effectiveRepoId)
  /** ≥2 个 = 子集联查（只读聚合） */
  const isJoint = computed(() => repo.isJoint)
  /** 勾选集合指纹：页面 watch 作用域变化一律用它 */
  const scopeKey = computed(() => repo.scopeKey)

  /**
   * 统一的作用域参数构造（**唯一构造点**）：勾 1 本 → `{repo_id}`；勾 ≥2 本 → `{repo_ids}`；
   * 没有已加载的库 → `{}`（不带库参数，由后端用活动书目）。可直接展开进请求参数：
   * `eventsApi.listEvents({ ...p, ...scope.repoParams() })`。
   */
  function repoParams(): RepoScopeParams {
    return repo.repoParams()
  }

  /** 写动作是否有唯一目标（联查态下没有——此时写动作只作用于**活动书目**） */
  const canWrite = computed(() => Boolean(effectiveRepoId.value))

  /**
   * 逐库取数用的目标库列表：给**没有 `repo_ids` 参数的端点**（回收站 / 备份清单 / 体检 /
   * 操作日志 / 概览统计）在前端 fan-out。空串 = 不带库参数，由后端用**活动书目**。
   * 勾选集合为空（登记表还没读回来 / 读取失败）时退回 `['']`，行为与旧版一致、不空白。
   */
  const readRepoIds = computed<string[]>(() =>
    selectedIds.value.length ? [...selectedIds.value] : [''],
  )

  /** 逐库取数时的显示名（空 id = 后端缺省的活动书目） */
  function repoLabel(repoId: string): string {
    return repoId ? repo.nameOf(repoId) : `活动书目《${repo.activeRepo?.name ?? '—'}》`
  }

  /**
   * 页面头部的作用域描述：联查态必须说出**具体是哪几个库**，
   * 不能再写成「全部书目（联查 N 本）」这种看不出勾了谁的口径。
   */
  const scopeLabel = computed(() => {
    const count = selectedIds.value.length
    if (count === 0) return '未选择书目（没有已加载的库）'
    if (count === 1) return `书目《${repo.nameOf(selectedIds.value[0])}》`
    const names = selectedNames.value.join('、')
    return `${names} ${CN_NUM[count] ?? String(count)}库（联查）`
  })

  return {
    repo,
    selectedIds,
    selectedRepos,
    selectedNames,
    effectiveRepoId,
    isJoint,
    scopeKey,
    repoParams,
    readRepoIds,
    repoLabel,
    canWrite,
    scopeLabel,
  }
}
