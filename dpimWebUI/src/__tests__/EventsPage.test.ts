import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/events', () => ({
  listEvents: vi.fn(),
  getEvent: vi.fn(),
  putEvent: vi.fn(),
  putEventStatus: vi.fn(),
  deleteEvent: vi.fn(),
  ingest: vi.fn(),
}))
vi.mock('@/api/repos', () => ({
  listRepos: vi.fn(),
  activateRepo: vi.fn(),
  generateRepo: vi.fn(),
  selectableRepos: (repos: any[]) => repos.filter((r: any) => r.managed && r.loaded),
}))
vi.mock('@/api/health', () => ({
  getHealth: vi.fn(),
  getStateHash: vi.fn(),
}))

import * as eventsApi from '@/api/events'
import * as repoApi from '@/api/repos'
import * as healthApi from '@/api/health'
import EventsPage from '@/pages/EventsPage.vue'
import { useRepoStore } from '@/stores/repo'

const Blank = defineComponent({ template: '<div />' })

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/events', name: 'events', component: Blank },
      { path: '/graph', name: 'graph', component: Blank },
      { path: '/', component: Blank },
    ],
  })
}

function repoRow(over: Record<string, unknown> = {}) {
  return {
    repo_id: 'rp_a',
    name: '书目甲',
    note: '',
    group: null,
    root_kind: 'managed',
    managed: true,
    active: true,
    loaded: true,
    total_events: 1,
    total_nodes: 1,
    db_path: '',
    json_path: '',
    created_at: '',
    updated_at: '',
    ...over,
  } as any
}

const EVENT_ROW = {
  event_id: 'ev_1',
  created_at: '2026-10-04T10:00:00Z',
  raw_content: '用户说他今天在写 DPIM 的前端',
  event_type: 'interaction',
  status: 'linked',
  repo_id: 'rp_a',
  repo_name: '书目甲',
}

async function mountPage() {
  const router = makeRouter()
  await router.push('/events')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(EventsPage) }),
  })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  await new Promise((r) => setTimeout(r, 0))
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  vi.mocked(repoApi.listRepos).mockResolvedValue({
    repos: [repoRow()],
    active_repo_id: 'rp_a',
  })
  vi.mocked(eventsApi.listEvents).mockResolvedValue({
    items: [EVENT_ROW] as never,
    total: 1,
    limit: 20,
    offset: 0,
  })
  vi.mocked(healthApi.getStateHash).mockResolvedValue({ hash: 'k', changed_at: '' } as never)
})

describe('EventsPage', () => {
  it('列出事件并标注原文 / 衍生两个区域', async () => {
    vi.mocked(eventsApi.getEvent).mockResolvedValue({
      ...EVENT_ROW,
      content_hash: 'h1',
      graph_refs: ['nd_1'],
    } as never)
    const store = useRepoStore()
    await store.load()

    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('信息列表')
    expect(eventsApi.listEvents).toHaveBeenCalled()

    // 点选一行 → 取详情 → 原文区与衍生区同时出现且文案区分
    await wrapper.find('tbody tr').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    expect(eventsApi.getEvent).toHaveBeenCalledWith('ev_1', 'rp_a')
    const text = wrapper.text()
    expect(text).toContain('仅人类可修订')
    expect(text).toContain('可由 AI 维护')
    expect(text).toContain('nd_1')
  })

  it('修订原文走人工通道并刷新状态密钥', async () => {
    vi.mocked(eventsApi.getEvent).mockResolvedValue({
      ...EVENT_ROW,
      content_hash: 'h1',
      graph_refs: [],
    } as never)
    vi.mocked(eventsApi.putEvent).mockResolvedValue({ message: 'ok' } as never)

    const store = useRepoStore()
    await store.load()
    const wrapper = await mountPage()
    await wrapper.find('tbody tr').trigger('click')
    await new Promise((r) => setTimeout(r, 0))

    const editBtn = wrapper.findAll('button').find((b) => b.text() === '修订')
    expect(editBtn).toBeTruthy()
    await editBtn!.trigger('click')

    const saveBtn = wrapper.findAll('button').find((b) => b.text() === '保存修订')
    await saveBtn!.trigger('click')
    await new Promise((r) => setTimeout(r, 0))

    expect(eventsApi.putEvent).toHaveBeenCalledWith(
      'ev_1',
      expect.objectContaining({ event_type: 'interaction' }),
    )
    // 写成功后刷新状态校验密钥（规约 §5.3）
    expect(healthApi.getStateHash).toHaveBeenCalled()
  })

  it('删除前弹二次确认，并说明会进回收站', async () => {
    vi.mocked(eventsApi.getEvent).mockResolvedValue({
      ...EVENT_ROW,
      content_hash: 'h1',
      graph_refs: [],
    } as never)
    const store = useRepoStore()
    await store.load()
    const wrapper = await mountPage()
    await wrapper.find('tbody tr').trigger('click')
    await new Promise((r) => setTimeout(r, 0))

    const delBtn = wrapper.findAll('button').find((b) => b.text() === '删除事件')
    await delBtn!.trigger('click')
    await new Promise((r) => setTimeout(r, 0))

    expect(eventsApi.deleteEvent).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('回收站')
  })

  it('联查（勾选 ≥2 本）下多出「来自书目」列（P5：结果必须能看出出处）', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repoRow(), repoRow({ repo_id: 'rp_b', name: '书目乙', active: false })],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    store.setSelection(['rp_a', 'rp_b'])

    const wrapper = await mountPage()
    const headers = wrapper.findAll('thead th').map((th) => th.text())
    expect(headers).toContain('来自书目')
    expect(eventsApi.listEvents).toHaveBeenCalledWith(
      expect.objectContaining({ repo_ids: ['rp_a', 'rp_b'] }),
    )
  })

  it('列表失败时把后端原文显示出来，而不是空白', async () => {
    vi.mocked(eventsApi.listEvents).mockRejectedValue(new Error('后端不可达：/events'))
    const store = useRepoStore()
    await store.load()
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('后端不可达')
  })
})
