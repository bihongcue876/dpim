import { describe, it, expect, vi } from 'vitest'
import { useListPage } from '@/composables/useListPage'

interface Row {
  id: string
}

describe('useListPage', () => {
  it('取数后填充 items/total，并把 filters 一并交给 fetch', async () => {
    const fetch = vi.fn().mockResolvedValue({ items: [{ id: 'a' }], total: 1 })
    const page = useListPage<Row, { q: string }>({
      fetch,
      initialFilters: { q: '' },
      pageSize: 20,
      immediate: false,
    })
    await page.load()
    expect(fetch).toHaveBeenCalledWith({ limit: 20, offset: 0, filters: { q: '' } })
    expect(page.items.value).toEqual([{ id: 'a' }])
    expect(page.total.value).toBe(1)
    expect(page.error.value).toBe('')
  })

  it('真分页：setOffset 以服务端 offset 重取', async () => {
    const fetch = vi.fn().mockResolvedValue({ items: [], total: 100 })
    const page = useListPage<Row, { q: string }>({
      fetch,
      initialFilters: { q: '' },
      pageSize: 20,
      immediate: false,
    })
    await page.setOffset(40)
    expect(page.offset.value).toBe(40)
    expect(fetch).toHaveBeenLastCalledWith({ limit: 20, offset: 40, filters: { q: '' } })
  })

  it('applyFilters 回到第一页；resetFilters 恢复初值', async () => {
    const fetch = vi.fn().mockResolvedValue({ items: [], total: 0 })
    const page = useListPage<Row, { q: string }>({
      fetch,
      initialFilters: { q: 'init' },
      immediate: false,
    })
    await page.setOffset(20)
    page.filters.q = 'hello'
    await page.applyFilters()
    expect(page.offset.value).toBe(0)
    expect(fetch).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, filters: { q: 'hello' } }),
    )

    await page.resetFilters()
    expect(page.filters.q).toBe('init')
  })

  it('三态互斥：有数据时 showEmpty 为假，即使正在加载也不显示首屏加载态', async () => {
    const fetch = vi.fn().mockResolvedValue({ items: [{ id: 'a' }], total: 1 })
    const page = useListPage<Row, { q: string }>({
      fetch,
      initialFilters: { q: '' },
      immediate: false,
    })
    await page.load()
    expect(page.showEmpty.value).toBe(false)

    // 第二次取数期间仍有旧数据 → 不显示空态，也不显示首屏加载态
    let release: (v: unknown) => void = () => {}
    const pending = new Promise((resolve) => {
      release = resolve
    })
    fetch.mockReturnValueOnce(pending)
    const loading = page.load()
    expect(page.showEmpty.value).toBe(false)
    expect(page.showLoading.value).toBe(false)
    release({ items: [{ id: 'b' }], total: 1 })
    await loading
  })

  it('失败时记录错误原文、清空数据，并让空态让位于错误态', async () => {
    const fetch = vi.fn().mockRejectedValue(new Error('后端不可达'))
    const page = useListPage<Row, { q: string }>({
      fetch,
      initialFilters: { q: '' },
      immediate: false,
    })
    await page.load()
    expect(page.error.value).toBe('后端不可达')
    expect(page.items.value).toEqual([])
    expect(page.showEmpty.value).toBe(false) // 错误态优先，不与空态同时出现
  })

  it('丢弃过期响应：先发起的请求后返回时不覆盖新结果', async () => {
    const resolvers: Array<(v: { items: Row[]; total: number }) => void> = []
    const fetch = vi.fn(
      () =>
        new Promise<{ items: Row[]; total: number }>((resolve) => {
          resolvers.push(resolve)
        }),
    )
    const page = useListPage<Row, { q: string }>({
      fetch,
      initialFilters: { q: '' },
      immediate: false,
    })

    const first = page.load() // 请求 1（旧）
    const second = page.load() // 请求 2（新）

    // 旧请求后到：必须被丢弃
    resolvers[0]({ items: [{ id: 'stale' }], total: 99 })
    await first
    expect(page.items.value).toEqual([])

    resolvers[1]({ items: [{ id: 'fresh' }], total: 1 })
    await second
    expect(page.items.value).toEqual([{ id: 'fresh' }])
    expect(page.total.value).toBe(1)
    expect(page.loading.value).toBe(false)
  })
})
