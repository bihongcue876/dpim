import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import GraphCanvas from '@/components/GraphCanvas.vue'

const nodes = [
  { node_id: 'n1', title: '节点一', node_type: 'data', confidence: 0.9 },
  { node_id: 'n2', title: '节点二', node_type: 'interaction', confidence: 0.8 },
]
const edges = [{ source: 'n1', target: 'n2', relation: '关联于', evidence_event_id: 'e1' }]

async function waitFrame() {
  await new Promise(r => requestAnimationFrame(r))
  await new Promise(r => setTimeout(r, 60))
}

/** jsdom 容器无布局尺寸，手动 mock 使 D3 build() 真正创建 SVG */
function sizeContainer(wrapper: ReturnType<typeof mount>) {
  Object.defineProperty(wrapper.element, 'clientWidth', { value: 400, configurable: true })
  Object.defineProperty(wrapper.element, 'clientHeight', { value: 300, configurable: true })
}

describe('GraphCanvas', () => {
  it('shows empty hint when no nodes', async () => {
    const wrapper = mount(GraphCanvas, {
      props: { nodes: [], edges: [], highlightNodeId: null },
    })
    await waitFrame()
    expect(wrapper.text()).toContain('暂无节点数据')
  })

  it('renders SVG when nodes provided', async () => {
    const wrapper = mount(GraphCanvas, {
      props: { nodes: [], edges: [], highlightNodeId: null },
    })
    await waitFrame()
    sizeContainer(wrapper)
    await wrapper.setProps({ nodes })
    await waitFrame()
    expect(wrapper.find('svg').exists()).toBe(true)
  })

  it('renders highlight glow for matching node', async () => {
    const wrapper = mount(GraphCanvas, {
      props: { nodes: [], edges: [], highlightNodeId: null },
    })
    await waitFrame()
    sizeContainer(wrapper)
    await wrapper.setProps({ nodes, edges, highlightNodeId: 'n1' })
    await waitFrame()
    expect(wrapper.find('svg').exists()).toBe(true)
    expect(wrapper.find('circle.glow').exists()).toBe(true)
  })

  it('rebuilds svg at new container size after refreshEpoch (panel collapse)', async () => {
    const wrapper = mount(GraphCanvas, {
      props: { nodes: [], edges: [], highlightNodeId: null },
    })
    await waitFrame()
    sizeContainer(wrapper)
    await wrapper.setProps({ nodes, edges })
    await waitFrame()
    const svgBefore = wrapper.find('svg')
    expect(svgBefore.attributes('width')).toBe('400')

    // 模拟面板收起：容器长高 + refreshEpoch+1（GraphTab 折叠面板时的联动）
    Object.defineProperty(wrapper.element, 'clientWidth', { value: 400, configurable: true })
    Object.defineProperty(wrapper.element, 'clientHeight', { value: 600, configurable: true })
    await wrapper.setProps({ refreshEpoch: 1 })
    // epoch 重建延迟 300ms（等 CSS 过渡结束）
    await new Promise(r => setTimeout(r, 450))

    const svgAfter = wrapper.find('svg')
    expect(svgAfter.exists()).toBe(true)
    expect(svgAfter.attributes('width')).toBe('400')
    expect(svgAfter.attributes('height')).toBe('600')
  })
})