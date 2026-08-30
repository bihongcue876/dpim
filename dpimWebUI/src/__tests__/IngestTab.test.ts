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
    last_event_at: '', version: '0.2.1',
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

const HEALTH_OK = {
  status: 'ok', ai_available: true,
  layers: {
    event_line: { total_events: 10 },
    knowledge_graph: { total_nodes: 3 },
  },
  last_event_at: '', version: '0.2.1',
}

const HEALTH_DOWN = {
  status: 'degraded', ai_available: false,
  layers: { event_line: {}, knowledge_graph: {} },
  last_event_at: '', version: '0.2.1',
}

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

  it('submit allowed when AI unavailable (degraded storage & commands)', async () => {
    ;(api.getHealth as any).mockResolvedValue(HEALTH_DOWN)
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('未连接上')
    const btn = wrapper.findAll('button').find(b => b.text().includes('提交处理'))!
    expect(btn.attributes('disabled')).toBeFalsy()
    // 降级态提交普通事件：入历史 + info 提示等待补偿
    ;(api.ingest as any).mockResolvedValue({ event_id: 'e-degraded', status: 'indexed' })
    const ta = wrapper.find('textarea')
    await ta.setValue('降级态内容')
    await btn.trigger('click')
    await new Promise(r => setTimeout(r, 50))
    expect(api.ingest).toHaveBeenCalledWith('降级态内容', 'interaction')
    const stored = JSON.parse(localStorage.getItem('dpim_ingest_history') || '[]')
    expect(stored.length).toBe(1)
  })

  it('command refused message path works when AI unavailable', async () => {
    ;(api.getHealth as any).mockResolvedValue(HEALTH_DOWN)
    ;(api.ingest as any).mockResolvedValue({
      event_id: '', status: 'skipped', command_triggered: true,
      message: '压缩指令未执行：AI 不可用或 Agent 管线未启用（^data 等纯存储指令不受影响）',
    })
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('^compress')
    await wrapper.findAll('button').find(b => b.text().includes('提交处理'))!.trigger('click')
    await new Promise(r => setTimeout(r, 50))
    expect(api.ingest).toHaveBeenCalledWith('^compress', 'interaction')
    expect((ta.element as HTMLTextAreaElement).value).toBe('')
    const stored = JSON.parse(localStorage.getItem('dpim_ingest_history') || '[]')
    expect(stored.length).toBe(0)
  })

  it('clears content with clear button', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('待清空')
    await wrapper.findAll('button').find(b => b.text().includes('清空内容'))!.trigger('click')
    expect((ta.element as HTMLTextAreaElement).value).toBe('')
  })

  it('command content triggers maintenance without history record', async () => {
    // 前序用例把 getHealth 覆盖为 AI 不可用（clearAllMocks 不还原实现），此处恢复
    ;(api.getHealth as any).mockResolvedValue(HEALTH_OK)
    ;(api.ingest as any).mockResolvedValue({
      event_id: '', status: 'skipped', command_triggered: true,
      message: '压缩指令已入队：扫描 → Gr 计划 → Meta 审核 → 执行',
    })
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('^compress')
    await wrapper.findAll('button').find(b => b.text().includes('提交处理'))!.trigger('click')
    await new Promise(r => setTimeout(r, 50))
    expect(api.ingest).toHaveBeenCalledWith('^compress', 'interaction')
    // 指令不进处理历史、不轮询（消息经 createDiscreteApi 渲染在挂载树外）
    const stored = JSON.parse(localStorage.getItem('dpim_ingest_history') || '[]')
    expect(stored.length).toBe(0)
    // 输入框已清空
    expect((ta.element as HTMLTextAreaElement).value).toBe('')
  })

  it('shows command hint line with caret syntax', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('支持指令')
    expect(wrapper.text()).toContain('^compress')
  })

  // ── 指令候选弹层（opencode 风格）──

  it('shows command candidates when typing caret', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('^')
    await new Promise(r => setTimeout(r, 20))
    const hints = wrapper.find('.cmd-hints')
    expect(hints.exists()).toBe(true)
    expect(hints.text()).toContain('^compress')
    expect(hints.text()).toContain('^help')
  })

  it('filters candidates by typed token', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('^co')
    await new Promise(r => setTimeout(r, 20))
    const hints = wrapper.find('.cmd-hints')
    expect(hints.exists()).toBe(true)
    expect(hints.text()).toContain('^compress')
    expect(hints.text()).not.toContain('^merge')
    expect(hints.text()).not.toContain('^help')
  })

  it('hides candidates for plain text and args phase', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('普通文本 ^ 不在开头')
    await new Promise(r => setTimeout(r, 20))
    expect(wrapper.find('.cmd-hints').exists()).toBe(false)
    // 空格后进入参数阶段：候选收起
    await ta.setValue('^data ')
    await new Promise(r => setTimeout(r, 20))
    expect(wrapper.find('.cmd-hints').exists()).toBe(false)
  })

  it('enter key selects candidate into input', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('^')
    await new Promise(r => setTimeout(r, 20))
    await ta.trigger('keydown', { key: 'Enter' })
    await new Promise(r => setTimeout(r, 20))
    // 第一候选 ^compress 填入（带尾随空格进入参数阶段，弹层收起）
    expect((ta.element as HTMLTextAreaElement).value).toBe('^compress ')
    expect(wrapper.find('.cmd-hints').exists()).toBe(false)
  })

  it('escape key dismisses candidates', async () => {
    const wrapper = mount(IngestTab)
    await new Promise(r => setTimeout(r, 50))
    const ta = wrapper.find('textarea')
    await ta.setValue('^')
    await new Promise(r => setTimeout(r, 20))
    expect(wrapper.find('.cmd-hints').exists()).toBe(true)
    await ta.trigger('keydown', { key: 'Escape' })
    await new Promise(r => setTimeout(r, 20))
    expect(wrapper.find('.cmd-hints').exists()).toBe(false)
  })
})
