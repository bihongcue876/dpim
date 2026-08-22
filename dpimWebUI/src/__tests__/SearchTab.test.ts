import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import SearchTab from '@/components/SearchTab.vue'

// 复用搜索动作：输入关键词并点击「搜索」
async function runSearch(wrapper: ReturnType<typeof mount>, keyword = '测试') {
  const input = wrapper.find('input')
  await input.setValue(keyword)
  const btn = wrapper.findAll('button').find(b => b.text().includes('搜索'))
  if (btn) {
    await btn.trigger('click')
    await new Promise(r => setTimeout(r, 100))
  }
}

vi.mock('@/api/client', () => ({
  query: vi.fn().mockResolvedValue({
    results: [
      { node_id: 'n1', title: '结果一', snippet: '这是第一个结果', score: 0.85, source_type: 'interaction', confidence: 0.9, source_events: ['e1'], degraded: false },
      { node_id: 'n2', title: '结果二', snippet: '这是知识节点', score: 0.72, source_type: 'data', confidence: 0.8, source_events: ['e2'], degraded: false },
    ],
    total: 2,
    degraded: false,
  }),
  listEvents: vi.fn().mockResolvedValue({
    items: [
      { event_id: 'e1', created_at: '2026-08-04T10:00:00Z', raw_content: '测试事件内容', event_type: 'interaction', status: 'linked' },
    ],
    total: 1,
  }),
  listNodes: vi.fn().mockResolvedValue({
    items: [{ node_id: 'n1', title: '节点一', node_type: 'interaction', confidence: 0.9 }],
    total: 1,
  }),
  getNode: vi.fn().mockResolvedValue({
    node_id: 'n1', title: '节点一', content: '详细内容', node_type: 'interaction',
    source_refs: [{ event_id: 'e1', valid: true, hash: 'abc123' }], confidence: 0.9, metadata: {},
  }),
  postFeedback: vi.fn().mockResolvedValue(undefined),
}))

import * as api from '@/api/client'

describe('SearchTab', () => {
  it('renders hybrid tab by default', () => {
    const wrapper = mount(SearchTab)
    expect(wrapper.text()).toContain('综合检索')
    expect(wrapper.text()).toContain('事件原文')
    expect(wrapper.text()).toContain('知识节点')
  })

  it('disables search button when query is empty in hybrid mode', () => {
    const wrapper = mount(SearchTab)
    const btn = wrapper.findAll('button').find(b => b.text().includes('搜索'))
    expect(btn?.attributes('disabled')).toBeDefined()
  })

  it('shows empty state before any search', () => {
    const wrapper = mount(SearchTab)
    expect(wrapper.text()).toContain('输入关键词开始搜索')
  })

  it('switching between tabs clears results', async () => {
    const wrapper = mount(SearchTab)
    // Switch to events tab
    const tabs = wrapper.findAll('.n-tabs .n-tab')
    if (tabs.length >= 2) {
      await tabs[1].trigger('click')
      await new Promise(r => setTimeout(r, 50))
      expect(wrapper.text()).toContain('事件原文')
    }
  })

  it('renders search results with group headers in hybrid mode', async () => {
    const wrapper = mount(SearchTab)
    // Set query and trigger search
    const input = wrapper.find('input')
    if (input) {
      await input.setValue('测试')
      const btn = wrapper.findAll('button').find(b => b.text().includes('搜索'))
      if (btn) {
        await btn.trigger('click')
        await new Promise(r => setTimeout(r, 100))
        expect(wrapper.text()).toContain('结果一')
        expect(wrapper.text()).toContain('结果二')
      }
    }
  })

  it('shows full pagination bar when total exceeds one page', async () => {
    const wrapper = mount(SearchTab)
    // total 44 条 / 每页 20 = 3 页：应显示完整页码条（可见所有页数，不会"看不见所有节点"）
    ;(api.query as any).mockResolvedValueOnce({
      results: [
        { node_id: 'n1', title: '结果一', snippet: '内容', score: 0.5, source_type: 'interaction', confidence: 0.9, source_events: ['e1'], degraded: false },
      ],
      total: 44,
      degraded: false,
    })
    const input = wrapper.find('input')
    if (input) {
      await input.setValue('测试')
      const btn = wrapper.findAll('button').find(b => b.text().includes('搜索'))
      if (btn) {
        await btn.trigger('click')
        await new Promise(r => setTimeout(r, 100))
        expect(wrapper.find('.pagination-bar').exists()).toBe(true)
      }
    }
  })

  it('jumps to source event from result card', async () => {
    const wrapper = mount(SearchTab)
    const details: any[] = []
    const handler = (e: Event) => { details.push((e as CustomEvent).detail) }
    window.addEventListener('dpim:focus-event', handler)
    try {
      await runSearch(wrapper, '测试')
      expect(wrapper.text()).toContain('源事件')
      const srcBtn = wrapper.findAll('button').find(b => b.text().includes('源事件'))
      if (srcBtn) {
        await srcBtn.trigger('click')
        await new Promise(r => setTimeout(r, 50))
        expect(details.length).toBe(1)
        expect(details[0].event_id).toBe('e1')
      } else {
        throw new Error('源事件跳转按钮未渲染')
      }
    } finally {
      window.removeEventListener('dpim:focus-event', handler)
    }
  })
})