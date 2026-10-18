/**
 * 列表分页取数（composable）：筛选 + 真分页（服务端 offset）+ 三态。
 *
 * 行为要求（规约 §5.8）：**三态互斥**——有结果时不显示空态
 * （旧版检索页空态无条件渲染，导致结果区只占一半高度）。
 * 因此空态判据统一由 `showEmpty` 给出，页面不要再自己写条件。
 */
import { computed, reactive, ref } from 'vue'
import type { Ref } from 'vue'

export interface ListPageFetchParams<F> {
  limit: number
  offset: number
  filters: F
}

export interface ListPageOptions<T, F extends Record<string, unknown>> {
  fetch: (params: ListPageFetchParams<F>) => Promise<{ items: T[]; total: number }>
  initialFilters: F
  pageSize?: number
  /** 挂载后自动取数（默认 true） */
  immediate?: boolean
}

export interface ListPage<T, F> {
  items: Ref<T[]>
  total: Ref<number>
  offset: Ref<number>
  pageSize: Ref<number>
  loading: Ref<boolean>
  error: Ref<string>
  filters: F
  /** 首屏加载中（尚无数据） */
  showLoading: Ref<boolean>
  /** 空态（无数据且非加载且无错误） */
  showEmpty: Ref<boolean>
  load: () => Promise<void>
  reload: () => Promise<void>
  setOffset: (value: number) => Promise<void>
  applyFilters: () => Promise<void>
  resetFilters: () => Promise<void>
}

export function useListPage<T, F extends Record<string, unknown>>(
  options: ListPageOptions<T, F>,
): ListPage<T, F> {
  const pageSize = ref(options.pageSize ?? 20)
  const items = ref<T[]>([]) as Ref<T[]>
  const total = ref(0)
  const offset = ref(0)
  const loading = ref(false)
  const error = ref('')
  const filters = reactive({ ...options.initialFilters }) as F

  const showLoading = computed(() => loading.value && items.value.length === 0)
  const showEmpty = computed(() => !loading.value && !error.value && items.value.length === 0)

  // 请求序号：快速切筛选/翻页/换书目时，旧响应可能后到并覆盖新结果（链 P10 同类问题）。
  // 只接受「最后一次发起」的响应，其余丢弃。
  let requestSeq = 0

  async function load(): Promise<void> {
    const seq = ++requestSeq
    loading.value = true
    try {
      const res = await options.fetch({
        limit: pageSize.value,
        offset: offset.value,
        filters: filters as F,
      })
      if (seq !== requestSeq) return
      items.value = res.items
      total.value = res.total
      error.value = ''
    } catch (e) {
      if (seq !== requestSeq) return
      error.value = (e as Error).message
      items.value = []
      total.value = 0
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  /** 回到第一页重取（筛选变化 / 写操作后调用） */
  async function reload(): Promise<void> {
    offset.value = 0
    await load()
  }

  async function setOffset(value: number): Promise<void> {
    offset.value = Math.max(0, value)
    await load()
  }

  async function applyFilters(): Promise<void> {
    await reload()
  }

  async function resetFilters(): Promise<void> {
    Object.assign(filters, options.initialFilters)
    await reload()
  }

  if (options.immediate !== false) void load()

  return {
    items,
    total,
    offset,
    pageSize,
    loading,
    error,
    filters,
    showLoading,
    showEmpty,
    load,
    reload,
    setOffset,
    applyFilters,
    resetFilters,
  }
}
