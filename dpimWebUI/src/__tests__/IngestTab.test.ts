import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import IngestTab from '@/components/IngestTab.vue'

vi.mock('@/api/client', () => ({
  getHealth: vi.fn().mockResolvedValue({
    status: 'ok', ai_available: true,
    layers: {
      event_line: { total_events: 10 },
      knowledge_graph: { total_nodes: 3 },
    },
    last_event_at: '', version: '0.2.0',
  }),
  getSettings: vi.fn().mockResolvedValue({
    llm_base_url: 'http://localhost:11434/v1', llm_model_name: 'llama3:8b',
  }),
  ingest: vi.fn().mockResolvedValue({ event_id: '1722000000000-abc', status: 'indexed' }),
  getEvent: vi.fn().mockResolvedValue({
    event_id: '1722000000000-abc', status: 'linked', graph_refs: ['n1', 'n2'],
  }),
}))

import * as api from '@/api/client'

describe('IngestTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('renders title and AI ready', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('AI 就绪')
    expect(wrapper.text()).toContain('提交处理')
  })

  it('submits content and adds history record', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('测试内容')
    await wrapper.findAll('button').find(b => b.text().includes('提交处理'))!.trigger('click')
    await new Promise(r => setTimeout(r, 50))
    // auto 模式已移除：默认提交 interaction 类型
    expect(api.ingest).toHaveBeenCalledWith('测试内容', 'interaction')
    expect(wrapper.text()).toContain('1722000000000-ab')
    // 已写入 localStorage
    const stored = JSON.parse(localStorage.getItem('dpim_ingest_history') || '[]')
    expect(stored.length).toBe(1)
    expect(stored[0].event_id).toBe('1722000000000-abc')
  })

  it('submit disabled when AI unavailable', async () => {
    ;(api.getHealth as any).mockResolvedValue({
      status: 'degraded', ai_available: false,
      layers: { event_line: {}, knowledge_graph: {} },
      last_event_at: '', version: '0.2.0',
    })
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('未连接上')
    const btn = wrapper.findAll('button').find(b => b.text().includes('提交处理'))!
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('clears content with clear button', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('待清空')
    await wrapper.findAll('button').find(b => b.text().includes('清空内容'))!.trigger('click')
    expect((ta.element as HTMLTextAreaElement).value).toBe('')
  })
})
