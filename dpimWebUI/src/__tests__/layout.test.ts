import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/repos', () => ({
  listRepos: vi.fn(),
  activateRepo: vi.fn(),
  selectableRepos: (repos: any[]) => repos.filter((r: any) => r.managed && r.loaded),
}))
vi.mock('@/api/health', () => ({
  getHealth: vi.fn(),
  getStateHash: vi.fn(),
}))

import * as repoApi from '@/api/repos'
import NavSidebar from '@/components/layout/NavSidebar.vue'
import RepoScopePicker from '@/components/layout/RepoScopePicker.vue'
import TopBar from '@/components/layout/TopBar.vue'
import { NAV_ZONES } from '@/router/nav'
import { SCOPE_STORAGE_KEY, useRepoStore } from '@/stores/repo'
import { useHealthStore } from '@/stores/health'

const Blank = defineComponent({ template: '<div />' })

/**
 * 书目选择器与顶栏都用到 `useMessage()`（作用域回退/「至少选一个」的提示）——
 * 没有 `n-message-provider` 时 naive-ui 会直接抛错，故统一包一层（与 App.vue 同构）。
 */
function mountIn(component: unknown, options: Record<string, unknown> = {}) {
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(component as never) }),
  })
  return mount(Host, options)
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: NAV_ZONES.flatMap((z) => z.items).map((i) => ({
      path: i.path,
      name: i.name,
      component: Blank,
    })),
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
    total_events: 0,
    total_nodes: 0,
    db_path: '',
    json_path: '',
    created_at: '',
    updated_at: '',
    ...over,
  } as any
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
})

describe('NavSidebar（四区分组导航）', () => {
  it('渲染四区 + 帮助，且每区标题来自 nav.ts', async () => {
    const router = makeRouter()
    await router.push('/overview')
    await router.isReady()
    const wrapper = mount(NavSidebar, { global: { plugins: [router] } })
    const titles = wrapper.findAll('.nav-zone-title').map((t) => t.text())
    expect(titles).toEqual(['观测', '查阅', '写入', '维护', '帮助'])
    expect(wrapper.findAll('.nav-item')).toHaveLength(12)
  })

  it('当前路由项带 router-link-active（导航可定位）', async () => {
    const router = makeRouter()
    await router.push('/repos')
    await router.isReady()
    const wrapper = mount(NavSidebar, { global: { plugins: [router] } })
    const active = wrapper.findAll('.nav-item.router-link-active')
    expect(active).toHaveLength(1)
    expect(active[0].text()).toBe('书目管理')
  })

  it('折叠状态持久化', async () => {
    const router = makeRouter()
    await router.push('/overview')
    await router.isReady()
    const wrapper = mount(NavSidebar, { global: { plugins: [router] } })
    await wrapper.find('.nav-collapse').trigger('click')
    expect(wrapper.classes()).toContain('nav--collapsed')
    expect(localStorage.getItem('dpim_nav_collapsed')).toBe('1')
  })
})

describe('RepoScopePicker（全局书目选择器：勾选子集）', () => {
  async function loadTwo() {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [
        repoRow({ repo_id: 'rp_a', active: true, group: '工作' }),
        repoRow({ repo_id: 'rp_b', name: '书目乙', active: false, group: '生活' }),
      ],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    return store
  }

  it('按书架列出全部书目，多选（multiple）——不再有「全部书目」这一项', async () => {
    await loadTwo()
    const wrapper = mountIn(RepoScopePicker)
    const picker = wrapper.findComponent({ name: 'Select' })
    expect(picker.props('multiple')).toBe(true)
    const options = picker.props('options') as any[]
    // 只有书架分组：没有「作用域 / 全部书目」那一组了
    expect(options.every((o) => o.type === 'group')).toBe(true)
    expect(options.map((o) => o.label)).toEqual(['书架 · 工作', '书架 · 生活'])
    const values = options.flatMap((o) => o.children.map((c: any) => c.value))
    expect(values).toEqual(['rp_a', 'rp_b'])
    expect(options.flatMap((o) => o.children).every((c: any) => c.disabled === false)).toBe(true)
  })

  it('休眠 / 未加载的书目禁用并写明原因（点得动却打不通是更坏的结果）', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [
        repoRow({ repo_id: 'rp_a' }),
        repoRow({ repo_id: 'rp_b', name: '休眠库', active: false, managed: false }),
        repoRow({ repo_id: 'rp_c', name: '未加载库', active: false, loaded: false }),
      ],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    const wrapper = mountIn(RepoScopePicker)
    const options = wrapper.findComponent({ name: 'Select' }).props('options') as any[]
    const children = options.flatMap((o) => o.children)
    const dormant = children.find((c: any) => c.value === 'rp_b')
    const unloaded = children.find((c: any) => c.value === 'rp_c')
    expect(dormant.disabled).toBe(true)
    expect(dormant.label).toContain('休眠')
    expect(unloaded.disabled).toBe(true)
    expect(unloaded.label).toContain('未加载')
  })

  it('勾选两本 = 联查：显示「联查 · 只读聚合」提示', async () => {
    const store = await loadTwo()
    store.setSelection(['rp_a', 'rp_b'])
    const wrapper = mountIn(RepoScopePicker)
    expect(wrapper.find('.picker-note').text()).toContain('只读聚合')
    expect(store.isJoint).toBe(true)
    expect(store.repoParams()).toEqual({ repo_ids: ['rp_a', 'rp_b'] })
  })

  it('勾选一本 = 单库：不再显示联查提示（单库快速切换的顺手感）', async () => {
    const store = await loadTwo()
    store.setSelection(['rp_b'])
    const wrapper = mountIn(RepoScopePicker)
    expect(wrapper.find('.picker-note').exists()).toBe(false)
    expect(store.effectiveRepoId).toBe('rp_b')
    expect(store.repoParams()).toEqual({ repo_id: 'rp_b' })
  })

  it('至少勾一本：取消最后一个保持原选中并给出提示（不出现「0 个库」）', async () => {
    const store = await loadTwo()
    store.setSelection(['rp_b'])
    const wrapper = mountIn(RepoScopePicker)
    wrapper.findComponent({ name: 'Select' }).vm.$emit('update:value', [])
    await new Promise((r) => setTimeout(r, 0))
    expect(store.selectedIds).toEqual(['rp_b'])
    expect(document.body.textContent).toContain('至少要选一个书目')
  })

  it('菜单底部有「全选 / 清空」快捷操作（清空至少留一本）', async () => {
    await loadTwo()
    const wrapper = mountIn(RepoScopePicker)
    const slots = wrapper.findComponent({ name: 'Select' }).vm.$slots as Record<string, unknown>
    expect(typeof slots.action).toBe('function')
  })

  it('持久化的库已失效 → 回退活动书目并给一次可见提示', async () => {
    localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(['rp_gone']))
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repoRow({ repo_id: 'rp_a', active: true })],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    expect(store.selectedIds).toEqual(['rp_a'])
    expect(store.scopeNotice).toContain('已回退到活动书目')

    mountIn(RepoScopePicker)
    await new Promise((r) => setTimeout(r, 0))
    expect(document.body.textContent).toContain('已回退到活动书目')
    expect(store.scopeNotice).toBe('') // 「一次」提示：消费后清掉，不重复弹
  })
})

describe('TopBar（常驻状态可见性）', () => {
  function mountWithHealth(status: string, aiAvailable: boolean, reason = '') {
    const health = useHealthStore()
    health.health = {
      status,
      ai_available: aiAvailable,
      ai_unavailable_reason: reason,
      layers: { event_line: {}, knowledge_graph: {} },
      last_event_at: '',
      version: '0.4.0',
      queue_depth: 4,
      worker_running: true,
    } as any
    health.connected = true
    return mountIn(TopBar, { global: { plugins: [makeRouter()] } })
  }

  it('连接 / AI / 队列 / 版本 全部常驻，不依赖具体页面', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repoRow()],
      active_repo_id: 'rp_a',
    })
    const repoStore = useRepoStore()
    await repoStore.load()

    const wrapper = mountWithHealth('degraded', false, 'AI 连接失败（连续 3 次）：APIConnectionError')
    const text = wrapper.text()
    expect(text).toContain('后端已连接')
    expect(text).toContain('AI 连不上 · 已降级')
    expect(text).toContain('队列 4')
    expect(text).toContain('v0.4.0')
    expect(text).toContain('本地小图书馆')
  })

  it('品牌标记用站点图标（与浏览器标签页同一个文件，不再是一块「DP」文字）', () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({ repos: [repoRow()], active_repo_id: 'rp_a' })
    const wrapper = mountIn(TopBar, { global: { plugins: [makeRouter()] } })
    const mark = wrapper.find('.brand-mark')
    expect(mark.element.tagName).toBe('IMG')
    // Vite 对 public 资产有两种处置：原样保留 `/favicon.svg`，或（小于内联阈值时）内联成 data URI。
    // 两种都指向同一份 `public/favicon.svg`，故断言「指向的确实是那张双区图标」，不钉死某一种形态。
    const src = mark.attributes('src') ?? ''
    if (src.startsWith('data:')) {
      expect(decodeURIComponent(src)).toContain('3ddbb0') // 图谱层节点色，favicon 独有
    } else {
      expect(src).toBe('/favicon.svg')
    }
    // 装饰性图标：读屏由旁边的「DPIM」承担，图标本身不进可访问性树
    expect(mark.attributes('aria-hidden')).toBe('true')
    expect(mark.text()).toBe('')
  })

  it('v1.34 三态：未配置 AI 与「连不上」文案必须不同（不把没配说成降级）', async () => {
    const unconfigured = mountWithHealth('unconfigured', false, '未配置任何 AI 提供商（无 AI 模式）')
    expect(unconfigured.text()).toContain('未配置 AI · 纯存储可用')
    expect(unconfigured.text()).not.toContain('已降级')

    const ready = mountWithHealth('ok', true)
    expect(ready.text()).toContain('AI 就绪')
  })

  it('主题切换按钮按当前模式给出可达性标签', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({ repos: [repoRow()], active_repo_id: 'rp_a' })
    const wrapper = mountIn(TopBar, { global: { plugins: [makeRouter()] } })
    const themeBtn = wrapper.findAll('button').find((b) => b.text().includes('亮色'))
    expect(themeBtn?.attributes('aria-label')).toBe('切换到亮色模式')
    await themeBtn!.trigger('click')
    expect(document.documentElement.dataset.dpimMode).toBe('light')
  })
})
