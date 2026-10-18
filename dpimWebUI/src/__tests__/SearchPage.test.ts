/**
 * 检索（SearchPage）页面级单测 —— 链 AE（§十 遗留待办 #5：剩余页面级单测）。
 *
 * 本页三种模式走**三个不同端点**（这是最容易接错的地方）：
 *   综合 hybrid → `POST /query`（带 source_filter / max_hops / repo_ids）
 *   原文 events → `GET /events?query`
 *   节点 nodes  → `GET /nodes?query`
 * 另守住：空关键词不请求（只提示）· 失败原文常驻 · 联查结果显示来源书目 ·
 * 降级明示（AI 不可用 → 全文检索）· 跨库反馈带 repo_id。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/search', () => ({ query: vi.fn() }))
vi.mock('@/api/events', () => ({ listEvents: vi.fn(), getEvent: vi.fn() }))
vi.mock('@/api/nodes', () => ({ listNodes: vi.fn(), getNode: vi.fn() }))

import * as searchApi from '@/api/search'
import * as eventsApi from '@/api/events'
import * as nodesApi from '@/api/nodes'
import SearchPage from '@/pages/SearchPage.vue'
import { useRepoStore } from '@/stores/repo'

const Blank = defineComponent({ template: '<div />' })
type Page = ReturnType<typeof mount>

function hybridResult(over: Record<string, unknown> = {}) {
  return {
    node_id: 'n1', title: '百度名字来源', snippet: '取自一句宋词', score: 0.42,
    confidence: 1, source_type: 'data', source_events: ['e1'], degraded: false,
    kind: 'node', repo_id: 'rp_default', repo_name: '默认库', source_repos: ['默认库'],
    ...over,
  } as never
}

async function flush(): Promise<void> {
  await flushPromises()
  await flushPromises()
}

async function mountPage(): Promise<Page> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/search', name: 'search', component: Blank },
      { path: '/events', name: 'events', component: Blank },
      { path: '/graph', name: 'graph', component: Blank },
    ],
  })
  await router.push('/search')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(SearchPage) }),
  })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  await flush()
  return wrapper
}

function button(page: Page, text: string): DOMWrapper<Element> {
  const hit = page.findAll('button').find((b) => b.text() === text)
  if (!hit) {
    const known = page.findAll('button').map((b) => b.text()).join(' / ')
    throw new Error(`未找到按钮「${text}」；现有：${known}`)
  }
  return hit
}

/** 输入关键词并点「检索」 */
async function searchFor(page: Page, keyword: string): Promise<void> {
  const input = page.find('input')
  await input.setValue(keyword)
  await button(page, '检索').trigger('click')
  await flush()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(searchApi.query).mockResolvedValue({
    results: [hybridResult()], total: 1, degraded: false, trace: null,
  } as never)
  vi.mocked(eventsApi.listEvents).mockResolvedValue({
    items: [{ event_id: 'e1', raw_content: '一段原文内容', event_type: 'data', status: 'linked',
              created_at: '', repo_id: 'rp_default', repo_name: '默认库' }],
    total: 1, limit: 20, offset: 0,
  } as never)
  vi.mocked(nodesApi.listNodes).mockResolvedValue({
    items: [{ node_id: 'n1', title: '百度名字来源', node_type: 'data', confidence: 1,
              repo_id: 'rp_default', repo_name: '默认库' }],
    total: 1, limit: 20, offset: 0,
  } as never)
  vi.mocked(nodesApi.getNode).mockResolvedValue({
    node_id: 'n1', title: '百度名字来源', content: '正文', node_type: 'data', confidence: 1,
    metadata: {}, source_refs: [{ event_id: 'e1', valid: true, hash: 'h' }],
    edges: [],
  } as never)
})

describe('SearchPage（检索）', () => {
  it('默认综合模式：POST /query 带筛选/跳数/分页，并显示结果与计数', async () => {
    const page = await mountPage()
    await searchFor(page, '百度')

    expect(searchApi.query).toHaveBeenCalledTimes(1)
    expect(vi.mocked(searchApi.query).mock.calls[0][0]).toMatchObject({
      query: '百度', source_filter: 'all', max_hops: 2, limit: 20, offset: 0,
    })
    const text = page.text()
    expect(text).toContain('百度名字来源')
    expect(text).toContain('共 1 条 · 第 1 / 1 页')
    expect(text).toContain('混合检索（全文 + 图扩散）')
    expect(text).toContain('默认库') // 来源书目锚定
  })

  it('空关键词：只提示、不发请求', async () => {
    const page = await mountPage()
    await button(page, '检索').trigger('click')
    await flush()

    expect(searchApi.query).not.toHaveBeenCalled()
    expect(page.text()).toContain('输入关键词开始检索')
  })

  it('原文模式走 GET /events?query（不是 /query）', async () => {
    const page = await mountPage()
    await searchFor(page, '原文')
    vi.clearAllMocks()

    // 切到「原文（事件）」：直接驱动 n-select 的 v-model（不开下拉面板，避免虚拟列表依赖）
    await page.findAllComponents({ name: 'Select' })[0].setValue('events', 'value')
    await flush()

    expect(eventsApi.listEvents).toHaveBeenCalledTimes(1)
    expect(vi.mocked(eventsApi.listEvents).mock.calls[0][0]).toMatchObject({ query: '原文' })
    expect(searchApi.query).not.toHaveBeenCalled()
    expect(page.text()).toContain('原文检索（全文）')
    expect(page.text()).toContain('一段原文内容')
  })

  it('节点模式走 GET /nodes?query，并补节点详情拿源事件', async () => {
    const page = await mountPage()
    await searchFor(page, '节点')
    vi.clearAllMocks()

    await page.findAllComponents({ name: 'Select' })[0].setValue('nodes', 'value')
    await flush()

    expect(nodesApi.listNodes).toHaveBeenCalledTimes(1)
    expect(vi.mocked(nodesApi.listNodes).mock.calls[0][0]).toMatchObject({ query: '节点' })
    expect(nodesApi.getNode).toHaveBeenCalled()
    expect(page.text()).toContain('衍生知识检索（全文）')
  })

  it('联查（勾选 ≥2 本）：把勾选书目的 repo_ids 传下去（不传单库 repo_id）', async () => {
    const repo = useRepoStore()
    repo.repos = [
      { repo_id: 'rp_a', name: '甲', managed: true, loaded: true, active: true, root_kind: 'managed' },
      { repo_id: 'rp_b', name: '乙', managed: true, loaded: true, active: false, root_kind: 'managed' },
    ] as never
    repo.setSelection(['rp_a', 'rp_b'])
    const page = await mountPage()
    await searchFor(page, '百度')

    const args = vi.mocked(searchApi.query).mock.calls[0][0]
    expect(args.repo_ids).toEqual(['rp_a', 'rp_b'])
  })

  it('勾 1 本 = 单库：POST /query 的 repo_ids 只带这一本（后端长度 1 即指定库检索）', async () => {
    const repo = useRepoStore()
    repo.repos = [
      { repo_id: 'rp_a', name: '甲', managed: true, loaded: true, active: true, root_kind: 'managed' },
      { repo_id: 'rp_b', name: '乙', managed: true, loaded: true, active: false, root_kind: 'managed' },
    ] as never
    repo.setSelection(['rp_b'])
    const page = await mountPage()
    await searchFor(page, '百度')

    expect(vi.mocked(searchApi.query).mock.calls[0][0].repo_ids).toEqual(['rp_b'])
    // 单库态不显示联查标记
    expect(page.text()).not.toContain('联查为只读聚合')
  })

  it('降级明示：AI 不可用 → 结果页显示「已用全文检索」', async () => {
    vi.mocked(searchApi.query).mockResolvedValue({
      results: [hybridResult()], total: 1, degraded: true, trace: null,
    } as never)
    const page = await mountPage()
    await searchFor(page, '百度')

    expect(page.text()).toContain('AI 不可用，已用全文检索')
  })

  it('失败：后端错误原文常驻页面（不是只在 toast 里闪）', async () => {
    vi.mocked(searchApi.query).mockRejectedValue(new Error('422: max_hops 超出范围'))
    const page = await mountPage()
    await searchFor(page, '百度')

    expect(page.text()).toContain('422: max_hops 超出范围')
  })

  it('无结果：给出「没有匹配结果」与可下手的建议', async () => {
    vi.mocked(searchApi.query).mockResolvedValue({
      results: [], total: 0, degraded: false, trace: null,
    } as never)
    const page = await mountPage()
    await searchFor(page, '查不到的东西')

    const text = page.text()
    expect(text).toContain('没有匹配结果')
    expect(text).toContain('图扩散跳数')
  })
})
