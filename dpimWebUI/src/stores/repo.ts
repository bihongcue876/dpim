/**
 * 全局书目作用域（store：repo）。
 *
 * 语义（设计规约 §2）：
 * - 书目（repo）= 小图书馆里的一本书 = 一 memory.db + 一 graph.json，完全隔离
 * - 分组（group）= 书架
 * - **书目是全局上下文，不是页面**：全站跟随顶栏一个选择器
 * - 作用域 = 用户在顶栏**自己勾选的库子集**（不是「单库 / 全部」两态）：
 *   勾 1 个 = 单库（写动作打它，读请求带 `repo_id`）；
 *   勾 ≥2 个 = 子集联查（读请求带 `repo_ids`，只读聚合）；
 *   **至少勾 1 个**（取消最后一个会被拒绝，不出现「0 个库」状态）。
 *
 * 勾选集合持久化在 localStorage（`dpim_repo_scope`，JSON 数组）；
 * 刷新后保持，其中已消失/未加载的库会被剔除并**回退到活动书目 + 给一次可见提示**。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as repoApi from '@/api/repos'
import type { RepoInfo } from '@/api/types'

/** 勾选集合的持久化键（JSON 数组；顺序不敏感——读取后一律按登记表顺序归一） */
export const SCOPE_STORAGE_KEY = 'dpim_repo_scope'

/** 作用域参数：单库 `repo_id` / 子集联查 `repo_ids`（后端只认这两种形态） */
export interface RepoScopeParams {
  repo_id?: string
  repo_ids?: string[]
}

export const useRepoStore = defineStore('repo', () => {
  const repos = ref<RepoInfo[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref('')
  /** 顶栏选择器的勾选集合（顺序稳定：一律按登记表顺序归一） */
  const selectedIds = ref<string[]>([])
  /** 一次性作用域提示（勾选集合被回退/剔除时报出来；界面消费后 clearScopeNotice()） */
  const scopeNotice = ref('')

  /** 是否已从 localStorage 恢复过（保证「刷新后保持」，且后续 load 不再覆盖用户勾选） */
  let hydrated = false

  const activeRepo = computed(() => repos.value.find((r) => r.active) ?? null)
  const activeRepoId = computed(() => activeRepo.value?.repo_id ?? '')

  /** 受管且已加载：可被检索/写入的书目（勾选与联查都只在这些库里发生） */
  const usableRepos = computed(() => repoApi.selectableRepos(repos.value))
  const usableIds = computed(() => usableRepos.value.map((r) => r.repo_id))

  const repoById = computed(() => {
    const map = new Map<string, RepoInfo>()
    for (const r of repos.value) map.set(r.repo_id, r)
    return map
  })

  function nameOf(repoId?: string): string {
    if (!repoId) return '未知书目'
    return repoById.value.get(repoId)?.name ?? repoId
  }

  /** 分组 → 书目（书架视图；无分组归入「未分组」） */
  const groups = computed(() => {
    const map = new Map<string, RepoInfo[]>()
    for (const r of repos.value) {
      const key = r.group?.trim() || '未分组'
      const list = map.get(key) ?? []
      list.push(r)
      map.set(key, list)
    }
    return [...map.entries()].map(([name, items]) => ({ name, items })).sort((a, b) => {
      if (a.name === '未分组') return 1
      if (b.name === '未分组') return -1
      return a.name.localeCompare(b.name, 'zh')
    })
  })

  const selectedRepos = computed(() =>
    usableRepos.value.filter((r) => selectedIds.value.includes(r.repo_id)),
  )

  /** 恰好勾 1 个 → 该库 id（写动作的目标、读请求的 `repo_id`）；否则空串 */
  const effectiveRepoId = computed(() =>
    selectedIds.value.length === 1 ? (selectedIds.value[0] ?? '') : '',
  )
  /** ≥2 个 = 子集联查（只读聚合） */
  const isJoint = computed(() => selectedIds.value.length > 1)
  /** 勾选集合的稳定指纹（watch 依赖用；数组本身每次都是新对象） */
  const scopeKey = computed(() => selectedIds.value.join(','))

  /** 统一的作用域参数构造（唯一构造点）：单库 `{repo_id}` / 联查 `{repo_ids}` / 无库 `{}` */
  function repoParams(): RepoScopeParams {
    if (selectedIds.value.length > 1) return { repo_ids: [...selectedIds.value] }
    const one = selectedIds.value[0]
    return one ? { repo_id: one } : {}
  }

  /** 归一：只留受管已加载的库，并按登记表顺序排列（同一集合的两种勾选顺序产出同一参数） */
  function normalizeScope(ids: string[]): string[] {
    const want = new Set(ids)
    return usableIds.value.filter((id) => want.has(id))
  }

  function isSelectable(repoId: string): boolean {
    return usableIds.value.includes(repoId)
  }

  function readPersisted(): string[] | null {
    try {
      const raw = localStorage.getItem(SCOPE_STORAGE_KEY)
      if (!raw) return null
      const parsed: unknown = JSON.parse(raw)
      if (!Array.isArray(parsed)) return null
      const ids = parsed.filter((v): v is string => typeof v === 'string' && v.length > 0)
      return ids.length ? ids : null
    } catch {
      // 隐私模式 / 坏 JSON：按「没存过」处理，绝不因为读偏好而让整页失败
      return null
    }
  }

  function persist(): void {
    try {
      localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(selectedIds.value))
    } catch {
      /* 同上：存不上也不影响本次会话 */
    }
  }

  /**
   * 设置勾选集合。**空集合被拒绝**（至少勾 1 个，不出现「0 个库」状态），返回 false。
   * 集合里不属于「受管且已加载」的库会被剔除（后端联查对这类库直接 422）。
   */
  function setSelection(ids: string[]): boolean {
    const next = normalizeScope(ids)
    if (!next.length) return false
    selectedIds.value = next
    persist()
    return true
  }

  /** 全选（受管已加载的库） */
  function selectAll(): void {
    if (!usableIds.value.length) return
    selectedIds.value = [...usableIds.value]
    persist()
  }

  /** 清空后回落到的那一本：活动书目（若可用）→ 否则第一本可用库 → 否则空 */
  const fallbackRepoId = computed(() => {
    const active = activeRepoId.value
    if (active && usableIds.value.includes(active)) return active
    return usableIds.value[0] ?? ''
  })

  /** 清空（至少留一本：回落活动书目）——返回是否真的变了 */
  function clearToFallback(): boolean {
    const target = fallbackRepoId.value
    if (!target) return false
    selectedIds.value = [target]
    persist()
    return true
  }

  /** 作用域提示消费完毕（界面弹过就清掉，保证「一次可见提示」不重复） */
  function clearScopeNotice(): void {
    scopeNotice.value = ''
  }

  /**
   * 把勾选集合对齐到当前登记表：
   * - 首次 load：从 localStorage 恢复；持久化的库已不存在/未加载 → 回退到活动书目 + 提示
   * - 之后 load：把已消失/被摘除/被卸载的库剔出集合（不静默留一个打不通的库）+ 提示
   */
  function reconcileScope(activeId: string): void {
    const stored = hydrated ? [...selectedIds.value] : (readPersisted() ?? [])
    hydrated = true
    const next = normalizeScope(stored)
    const dropped = [...new Set(stored)].filter((id) => !next.includes(id))
    const fallback = usableIds.value.includes(activeId) ? activeId : (usableIds.value[0] ?? '')
    if (!next.length) {
      selectedIds.value = fallback ? [fallback] : []
      if (dropped.length) {
        scopeNotice.value = fallback
          ? `上次选中的书目已不存在或未加载（${dropped.map((id) => nameOf(id)).join('、')}）——已回退到活动书目《${nameOf(fallback)}》`
          : `上次选中的书目已不存在或未加载（${dropped.map((id) => nameOf(id)).join('、')}），且当前没有已加载的书目`
      }
    } else {
      selectedIds.value = next
      if (dropped.length) {
        scopeNotice.value = `已从书目作用域移除不可用的库（${dropped.map((id) => nameOf(id)).join('、')}）`
      }
    }
    persist()
  }

  async function load(): Promise<void> {
    loading.value = true
    try {
      const res = await repoApi.listRepos()
      repos.value = res.repos
      loaded.value = true
      error.value = ''
      reconcileScope(res.active_repo_id || '')
    } catch (e) {
      error.value = (e as Error).message
      loaded.value = false
    } finally {
      loading.value = false
    }
  }

  /** 切换活动书目（写操作的前提）：成功后重载清单，并把作用域收拢到它（单库顺手） */
  async function activate(repoId: string): Promise<void> {
    await repoApi.activateRepo(repoId)
    await load() // 内部已按新登记表对齐勾选集合，绝不留下打不通的库
    if (isSelectable(repoId)) {
      selectedIds.value = [repoId]
      persist()
    }
  }

  return {
    repos,
    loading,
    loaded,
    error,
    selectedIds,
    scopeNotice,
    activeRepo,
    activeRepoId,
    usableRepos,
    usableIds,
    repoById,
    groups,
    selectedRepos,
    effectiveRepoId,
    isJoint,
    scopeKey,
    fallbackRepoId,
    repoParams,
    isSelectable,
    setSelection,
    selectAll,
    clearToFallback,
    clearScopeNotice,
    nameOf,
    load,
    activate,
  }
})
