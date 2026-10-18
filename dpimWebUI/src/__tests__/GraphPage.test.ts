/**
 * 信息图谱页（GraphPage）取边路径 —— v1.37 `GET /edges`。
 *
 * 覆盖本轮的真缺陷修复：此前**没有边列表端点**，页面只能「先取节点列表、再逐节点
 * `GET /nodes/{id}` 汇总边」——400 节点 ≈ 17 批请求，且每批 `.catch(() => null)`，
 * 任一节点详情失败就**静默少一批边**（图看起来只是不连通，没有任何提示）。
 * 现在改为一次 `listEdges` 取全，且边失败必须**显式可见**。
 *
 * 本文件只验证取数路径（D3 渲染另有 GraphCanvas.test.ts）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h, nextTick } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/nodes', () => ({
  listNodes: vi.fn(),
  listEdges: vi.fn(),
  getNode: vi.fn(),
  createNode: vi.fn(),
  putNode: vi.fn(),
  deleteNode: vi.fn(),
  createEdge: vi.fn(),
  deleteEdge: vi.fn(),
  clearGraph: vi.fn(),
  addNodeSourceRef: vi.fn(),
  removeNodeSourceRef: vi.fn(),
}))

import * as nodesApi from '@/api/nodes'
import GraphPage from '@/pages/GraphPage.vue'

const Blank = defineComponent({ template: '<div />' })
/** 画布换哑元：本文件不测渲染 */
const CANVAS_STUB = defineComponent({
  name: 'GraphCanvas',
  props: ['nodes', 'edges'],
  template: '<div class="canvas-stub" />',
})

function node(id: string, title: string) {
  return {
    node_id: id,
    title,
    node_type: 'data',
    confidence: 0.5,
    repo_id: 'rp_a',
    repo_name: '书目甲',
  } as never
}

function edge(source: string, target: string, relation = '关联') {
  return {
    source,
    target,
    relation,
    evidence_event_id: 'e1',
    repo_id: 'rp_a',
    repo_name: '书目甲',
  } as never
}

function page(total: number, items: unknown[]) {
  return { items, total, limit: 2000, offset: 0 } as never
}

async function flush() {
  await nextTick()
  await new Promise((r) => setTimeout(r, 0))
  await nextTick()
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/graph', name: 'graph', component: Blank }],
  })
  await router.push('/graph')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(GraphPage) }),
  })
  const wrapper = mount(Host, {
    global: { plugins: [router], stubs: { GraphCanvas: CANVAS_STUB } },
  })
  await flush()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
})

describe('GraphPage 取边（GET /edges，v1.37）', () => {
  it('一次 listEdges 取全：不再逐节点 getNode 汇总边，且只数「画得出」的边', async () => {
    vi.mocked(nodesApi.listNodes).mockResolvedValue(
      page(2, [node('n1', '甲'), node('n2', '乙')]) as never,
    )
    // 第二条边指向一个不在节点列表里的 id（图里残留的悬空端点）→ 画布画不出
    vi.mocked(nodesApi.listEdges).mockResolvedValue(
      page(2, [edge('n1', 'n2'), edge('n1', 'n_missing')]) as never,
    )

    const wrapper = await mountPage()

    expect(nodesApi.listEdges).toHaveBeenCalledTimes(1)
    expect(nodesApi.getNode).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('关联 1')
    expect(wrapper.text()).toContain('另有 1 条边的端点不在已加载节点里，未绘制')
    expect(wrapper.text()).not.toContain('边已截断')
    // 作用域参数与节点列表同源（单库 repo_id；库登记未装载时为空）
    expect(vi.mocked(nodesApi.listEdges).mock.calls[0][0]).toMatchObject({ limit: 2000 })
  })

  it('边数被 limit 截断时显式说明（已取前 N / 共 M）', async () => {
    vi.mocked(nodesApi.listNodes).mockResolvedValue(
      page(2, [node('n1', '甲'), node('n2', '乙')]) as never,
    )
    vi.mocked(nodesApi.listEdges).mockResolvedValue(
      page(5, [edge('n1', 'n2'), edge('n2', 'n1', '反向')]) as never,
    )

    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('边已截断')
    expect(wrapper.text()).toContain('已取前 2')
    expect(wrapper.text()).toContain('共 5')
  })

  it('边取失败仍显示节点，并把失败原因显式报出（不静默丢边）', async () => {
    vi.mocked(nodesApi.listNodes).mockResolvedValue(
      page(2, [node('n1', '甲'), node('n2', '乙')]) as never,
    )
    vi.mocked(nodesApi.listEdges).mockRejectedValue(new Error('500 Internal Server Error'))

    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('节点 2 / 2')
    expect(wrapper.text()).toContain('边列表获取失败')
    expect(wrapper.text()).toContain('500 Internal Server Error')
  })

  it('节点列表本身失败时不请求边，错误原样展示', async () => {
    vi.mocked(nodesApi.listNodes).mockRejectedValue(new Error('503 Storage not initialized'))

    const wrapper = await mountPage()

    expect(nodesApi.listEdges).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('503 Storage not initialized')
  })
})

/** 页面内的按钮（弹窗在 body 里，同文案的按钮要用 clickDialogButton） */
function button(wrapper: ReturnType<typeof mount>, text: string) {
  const hit = wrapper.findAll('button').find((b) => b.text() === text)
  if (!hit) {
    throw new Error(`未找到按钮「${text}」；现有：${wrapper.findAll('button').map((b) => b.text()).join(' / ')}`)
  }
  return hit
}

function dialogText(): string {
  return document.querySelector('.confirm')?.textContent ?? ''
}

function clickDialogButton(text: string): void {
  const btns = Array.from(document.querySelectorAll('.confirm-actions button'))
  const hit = btns.find((b) => (b.textContent ?? '').trim() === text) as HTMLElement | undefined
  if (!hit) {
    throw new Error(`弹窗里未找到按钮「${text}」；现有：${btns.map((b) => b.textContent?.trim()).join(' / ')}`)
  }
  hit.click()
}

describe('GraphPage 清空图层（DELETE /graph，v1.42）', () => {
  function clearResult(over: Record<string, unknown> = {}) {
    return {
      message: '图层已清空（2 节点 / 1 边）；已留档 graph-20261017-144222（回收站可恢复）；'
        + '2 条事件回到「待处理」（可重新入图）',
      archived: true,
      archive_id: 'graph-20261017-144222',
      cleared_nodes: 2,
      cleared_edges: 1,
      unlinked_events: 2,
      relinked_events: 2,
      ...over,
    } as never
  }

  async function openClearDialog() {
    vi.mocked(nodesApi.listNodes).mockResolvedValue(
      page(2, [node('n1', '甲'), node('n2', '乙')]) as never,
    )
    vi.mocked(nodesApi.listEdges).mockResolvedValue(
      page(1, [edge('n1', 'n2')]) as never,
    )
    const wrapper = await mountPage()
    await button(wrapper, '清空图层').trigger('click')
    await flush()
    return wrapper
  }

  it('二次确认改为「已留档可恢复 + 事件回到待处理」，不再写「不可逆」', async () => {
    await openClearDialog()

    const text = dialogText()
    expect(text).toContain('清空图层？')
    expect(text).toContain('自动留档整图')
    expect(text).toContain('回收站')
    expect(text).toContain('回到「待处理」')
    expect(text).not.toContain('不可逆')
  })

  it('留档成功：透出后端 message（计数 + 留档 ID + 可恢复）', async () => {
    vi.mocked(nodesApi.clearGraph).mockResolvedValue(clearResult())
    await openClearDialog()

    clickDialogButton('清空图层')
    await flush()

    expect(nodesApi.clearGraph).toHaveBeenCalledTimes(1)
    expect(document.body.textContent).toContain('已留档 graph-20261017-144222')
    expect(document.body.textContent).toContain('2 条事件回到「待处理」')
  })

  it('留档失败：以 error 级提示「不可恢复」，不让用户以为还能从回收站找回', async () => {
    vi.mocked(nodesApi.clearGraph).mockResolvedValue(clearResult({
      message: '图层已清空（2 节点 / 1 边）；留档失败，此操作不可恢复',
      archived: false,
      archive_id: '',
      unlinked_events: 0,
      relinked_events: 0,
    }))
    await openClearDialog()

    clickDialogButton('清空图层')
    await flush()

    expect(document.body.textContent).toContain('留档失败，此操作不可恢复')
    expect(document.body.querySelector('.n-message--error-type')).toBeTruthy()
  })

  it('清空失败：后端原文进页面错误条（不静默）', async () => {
    vi.mocked(nodesApi.clearGraph).mockRejectedValue(new Error('409: 清空被拒绝'))
    const wrapper = await openClearDialog()

    clickDialogButton('清空图层')
    await flush()

    // 错误条在页面里（mount 默认不挂到 body，故查 wrapper 而非 document.body）
    expect(wrapper.text()).toContain('409: 清空被拒绝')
  })
})
