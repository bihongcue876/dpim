import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import GraphTab from '@/components/GraphTab.vue'

vi.mock('@/api/client', () => ({
  listNodes: vi.fn().mockResolvedValue({
    items: [
      { node_id: 'n1', title: '概念A', node_type: 'data', confidence: 0.9 },
      { node_id: 'n2', title: '概念B', node_type: 'interaction', confidence: 0.8 },
    ],
    total: 2,
  }),
  getNode: vi.fn().mockImplementation((id: string) => {
    if (id === 'n1') return Promise.resolve({
      node_id: 'n1', title: '概念A', content: 'A的详细内容', node_type: 'data',
      confidence: 0.9, metadata: { evidence_quote: '引用', tags: [], protected: false, conflict: false },
      source_refs: [{ event_id: 'e1', valid: true, hash: 'abc' }],
      edges: [{ source: 'n1', target: 'n2', relation: '关联于', evidence_event_id: 'e1' }],
    })
    return Promise.resolve({
      node_id: 'n2', title: '概念B', content: 'B的详细内容', node_type: 'interaction',
      confidence: 0.8, metadata: { evidence_quote: '引用', tags: [], protected: false, conflict: false },
      source_refs: [{ event_id: 'e1', valid: true, hash: 'abc' }],
      edges: [{ source: 'n1', target: 'n2', relation: '关联于', evidence_event_id: 'e1' }],
    })
  }),
  listEvents: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  createNode: vi.fn().mockResolvedValue({ node_id: 'n3' }),
  createEdge: vi.fn().mockResolvedValue(undefined),
  deleteNode: vi.fn().mockResolvedValue(undefined),
  deleteEdge: vi.fn().mockResolvedValue(undefined),
  putNode: vi.fn().mockResolvedValue(undefined),
  clearGraph: vi.fn().mockResolvedValue(undefined),
  addNodeSourceRef: vi.fn().mockResolvedValue(undefined),
  removeNodeSourceRef: vi.fn().mockResolvedValue(undefined),
}))

import * as api from '@/api/client'

describe('GraphTab', () => {
  it('renders node list on mount', async () => {
    const wrapper = mount(GraphTab, {
      props: { keyStatus: '' },
    })
    await new Promise(r => setTimeout(r, 100))
    expect(wrapper.text()).toContain('概念A')
    expect(wrapper.text()).toContain('概念B')
    expect(api.listNodes).toHaveBeenCalled()
  })

  it('toggles panel open/close', async () => {
    const wrapper = mount(GraphTab, {
      props: { keyStatus: '' },
    })
    await new Promise(r => setTimeout(r, 100))
    const panelBtn = wrapper.findAll('button').find(b => b.text().includes('收起面板') || b.text().includes('展开面板'))
    expect(panelBtn).toBeTruthy()
  })

  it('shows node detail on click', async () => {
    const wrapper = mount(GraphTab, {
      props: { keyStatus: '' },
    })
    await new Promise(r => setTimeout(r, 100))
    // Find a node in the node list and click it
    const nodeRow = wrapper.findAll('.node-mini-row')[0]
    await nodeRow.trigger('click')
    await new Promise(r => setTimeout(r, 100))
    expect(api.getNode).toHaveBeenCalledWith('n1')
  })

  it('shows create node form fields', () => {
    const wrapper = mount(GraphTab, {
      props: { keyStatus: '' },
    })
    expect(wrapper.text()).toContain('新建节点')
    expect(wrapper.text()).toContain('添加关联')
  })

  it('node detail shows source ref management with min-1 guard', async () => {
    const wrapper = mount(GraphTab, {
      props: { keyStatus: '' },
    })
    await new Promise(r => setTimeout(r, 100))
    await wrapper.findAll('.node-mini-row')[0].trigger('click')
    await new Promise(r => setTimeout(r, 100))
    // n1 仅 1 条有效源证 → 移除按钮禁用（最少保留 1 条有效源事件）
    expect(wrapper.text()).toContain('至少保留 1 条有效')
    const removeBtn = wrapper.findAll('button').find(b => b.text().includes('移除'))
    expect(removeBtn).toBeTruthy()
    expect(removeBtn!.attributes('disabled')).toBeDefined()
    // 添加入口存在
    expect(wrapper.text()).toContain('关联源事件')
    // 空输入时添加按钮禁用
    const addBtn = wrapper.findAll('button').find(b => b.text().includes('关联源事件'))!
    expect(addBtn.attributes('disabled')).toBeDefined()
  })

  it('adds source ref via api', async () => {
    // 让 n1 有两条有效源证 → 移除可用，添加可用
    ;(api.getNode as any).mockImplementation((id: string) => {
      if (id === 'n1') return Promise.resolve({
        node_id: 'n1', title: '概念A', content: 'A的详细内容', node_type: 'data',
        confidence: 0.9, metadata: { evidence_quote: '引用', tags: [], protected: false, conflict: false },
        source_refs: [
          { event_id: 'e1', valid: true, hash: 'abc' },
          { event_id: 'e2', valid: true, hash: 'def' },
        ],
        edges: [],
      })
      return Promise.resolve({
        node_id: 'n2', title: '概念B', content: 'B的详细内容', node_type: 'interaction',
        confidence: 0.8, metadata: { evidence_quote: '引用', tags: [], protected: false, conflict: false },
        source_refs: [{ event_id: 'e1', valid: true, hash: 'abc' }],
        edges: [],
      })
    })
    const wrapper = mount(GraphTab, {
      props: { keyStatus: '' },
    })
    await new Promise(r => setTimeout(r, 100))
    await wrapper.findAll('.node-mini-row')[0].trigger('click')
    await new Promise(r => setTimeout(r, 100))
    const inputs = wrapper.findAll('input')
    const addInput = inputs.find(i => (i.element as HTMLInputElement).placeholder?.includes('事件 ID'))
    expect(addInput).toBeTruthy()
    ;(addInput!.element as HTMLInputElement).value = 'e9'
    await addInput!.setValue('e9')
    const addBtn = wrapper.findAll('button').find(b => b.text().includes('关联源事件'))!
    await addBtn.trigger('click')
    await new Promise(r => setTimeout(r, 100))
    expect(api.addNodeSourceRef).toHaveBeenCalledWith('n1', 'e9')
  })

  it('remove button enabled when more than one valid ref', async () => {
    ;(api.getNode as any).mockImplementation((id: string) => {
      if (id === 'n1') return Promise.resolve({
        node_id: 'n1', title: '概念A', content: 'A', node_type: 'data',
        confidence: 0.9, metadata: { evidence_quote: 'x', tags: [], protected: false, conflict: false },
        source_refs: [
          { event_id: 'e1', valid: true, hash: 'abc' },
          { event_id: 'e2', valid: true, hash: 'def' },
        ],
        edges: [],
      })
      return Promise.resolve({
        node_id: 'n2', title: '概念B', content: 'B', node_type: 'interaction',
        confidence: 0.8, metadata: { evidence_quote: 'x', tags: [], protected: false, conflict: false },
        source_refs: [{ event_id: 'e1', valid: true, hash: 'abc' }],
        edges: [],
      })
    })
    const wrapper = mount(GraphTab, {
      props: { keyStatus: '' },
    })
    await new Promise(r => setTimeout(r, 100))
    await wrapper.findAll('.node-mini-row')[0].trigger('click')
    await new Promise(r => setTimeout(r, 100))
    const removeBtns = wrapper.findAll('button').filter(b => b.text() === '移除')
    expect(removeBtns.length).toBe(2)
    // 两条有效源证 → 均可移除（移除后仍剩一条）
    expect(removeBtns[0].attributes('disabled')).toBeUndefined()
    expect(removeBtns[1].attributes('disabled')).toBeUndefined()
    await removeBtns[0].trigger('click')
    await new Promise(r => setTimeout(r, 100))
    expect(api.removeNodeSourceRef).toHaveBeenCalledWith('n1', 'e1')
  })
})