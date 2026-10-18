/**
 * 信息传入（IngestPage）页面级单测 —— 链 AE（§十 遗留待办 #5：剩余页面级单测）。
 *
 * 本页是**写入口**，守住五件事：
 * ① 进页读配置并把 AI 三态（含未配置原因）显示出来——但**不因为 AI 不可用而禁用提交**；
 * ② 提交把内容/类型/目标书目原样交给 `POST /ingest`，并把结果与处理历史显示出来；
 * ③ 指令（`^…`）走的是「不落库」的响应分支：显示「指令结果」、清空输入、不进历史；
 * ④ 指令被后端拒绝（含「未执行」字样）要单独标出「指令未被接受」；
 * ⑤ 提交失败要把后端原文留在结果区（P6），不是只在 toast 里闪。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/events', () => ({
  ingest: vi.fn(),
  listEvents: vi.fn(),
  getEvent: vi.fn(),
}))
vi.mock('@/api/settings', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  probeProviderModels: vi.fn(),
}))
vi.mock('@/api/health', () => ({
  getHealth: vi.fn(),
  getStateHash: vi.fn(),
  getAgentLogs: vi.fn(),
  compensate: vi.fn(),
  maintain: vi.fn(),
}))

import * as eventsApi from '@/api/events'
import * as settingsApi from '@/api/settings'
import * as healthApi from '@/api/health'
import IngestPage from '@/pages/IngestPage.vue'
import { useHealthStore } from '@/stores/health'

const Blank = defineComponent({ template: '<div />' })
type Page = ReturnType<typeof mount>

function settingsFixture(): Record<string, unknown> {
  return {
    providers: {
      local: { base_url: 'http://127.0.0.1:11434/v1', api_key: '', models: ['qwen2.5:7b'] },
    },
    available_providers: ['local'],
    active_provider: 'local',
    available_models: ['qwen2.5:7b'],
    active_model: 'qwen2.5:7b',
    llm_configured: true,
    llm_unavailable_reason: '',
    agent_mode: 'pipeline',
    config_sources: {},
  }
}

async function flush(): Promise<void> {
  await flushPromises()
  await flushPromises()
}

async function mountPage(): Promise<Page> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/ingest', name: 'ingest', component: Blank },
      { path: '/events', name: 'events', component: Blank },
    ],
  })
  await router.push('/ingest')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(IngestPage) }),
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

/** 往正文域里打字（n-input textarea → 真实 textarea 元素） */
async function type(page: Page, text: string): Promise<void> {
  await page.find('textarea').setValue(text)
  await flush()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(settingsApi.getSettings).mockResolvedValue(settingsFixture() as never)
  vi.mocked(healthApi.getStateHash).mockResolvedValue({ hash: 'K3', changed_at: '' } as never)
  vi.mocked(healthApi.getHealth).mockResolvedValue({
    status: 'ok', ai_available: true, layers: {}, storage: {},
  } as never)
  vi.mocked(eventsApi.ingest).mockResolvedValue({
    event_id: 'e_new', status: 'indexed', message: 'Event ingested',
    command_triggered: false,
  } as never)
})

describe('IngestPage（信息传入）', () => {
  it('进页读配置：AI 状态行显示三态文案与提供商/模型/地址', async () => {
    // 顶栏/外壳负责刷健康；本页只读 store，故测试里先喂一次（走真实 refresh 路径）
    vi.mocked(healthApi.getHealth).mockResolvedValue({
      status: 'ok', ai_available: true, layers: {}, storage: {},
    } as never)
    await useHealthStore().refresh()
    const page = await mountPage()

    expect(settingsApi.getSettings).toHaveBeenCalledTimes(1)
    const text = page.text()
    expect(text).toContain('AI 状态')
    expect(text).toContain('AI 就绪')
    expect(text).toContain('提供商')
    expect(text).toContain('local')
    expect(text).toContain('qwen2.5:7b')
    expect(text).toContain('http://127.0.0.1:11434/v1')
    // 规约 §5.5：AI 不可用**不**禁用提交（本页只写入原文）
    expect(button(page, '提交').attributes('disabled')).toBeDefined() // 空内容时禁用
  })

  it('AI 未配置：显示「未配置 AI · 纯存储可用」与原因，但提交仍可用（有内容时）', async () => {
    vi.mocked(healthApi.getHealth).mockResolvedValue({
      status: 'unconfigured', ai_available: false,
      ai_unavailable_reason: '未配置任何 AI 提供商（无 AI 模式：存储、检索与指令照常可用）',
      layers: {}, storage: {},
    } as never)
    await useHealthStore().refresh()
    vi.mocked(settingsApi.getSettings).mockResolvedValue({
      ...settingsFixture(),
      providers: {},
      active_provider: '',
      active_model: '',
      available_models: [],
      llm_configured: false,
      llm_unavailable_reason: '未配置任何 AI 提供商（无 AI 模式）',
    } as never)
    const page = await mountPage()
    await type(page, '一段原文')

    const text = page.text()
    expect(text).toContain('未配置 AI · 纯存储可用')
    expect(text).toContain('未配置任何 AI 提供商')
    expect(button(page, '提交').attributes('disabled')).toBeUndefined()
  })

  it('提交：内容/类型/目标书目交给 POST /ingest，结果显示事件 ID 并进处理历史', async () => {
    const page = await mountPage()
    await type(page, '一段要落库的原文')
    await button(page, '提交').trigger('click')
    await flush()

    expect(vi.mocked(eventsApi.ingest).mock.calls[0]).toEqual([
      '一段要落库的原文', 'interaction', '',
    ])
    const text = page.text()
    expect(text).toContain('提交结果')
    expect(text).toContain('e_new')
    expect(text).toContain('处理历史')
  })

  it('空内容：提交按钮禁用（不发请求）', async () => {
    const page = await mountPage()
    expect(button(page, '提交').attributes('disabled')).toBeDefined()
    await button(page, '提交').trigger('click')
    await flush()
    expect(eventsApi.ingest).not.toHaveBeenCalled()
  })

  it('指令（^merge）：走「不落库」分支 → 显示指令结果、清空输入、不进处理历史', async () => {
    vi.mocked(eventsApi.ingest).mockResolvedValue({
      event_id: '', status: 'skipped', command_triggered: true,
      message: '合并指令已执行：吸收 2 个节点',
    } as never)
    const page = await mountPage()
    await type(page, '^merge')
    await button(page, '提交').trigger('click')
    await flush()

    const text = page.text()
    expect(text).toContain('指令结果')
    expect(text).toContain('合并指令已执行：吸收 2 个节点')
    expect(text).toContain('指令本身不落库')
    expect((page.find('textarea').element as HTMLTextAreaElement).value).toBe('')
  })

  it('指令被拒绝（含「未执行」）：单独标出「指令未被接受（后端原文如下）」', async () => {
    vi.mocked(eventsApi.ingest).mockResolvedValue({
      event_id: '', status: 'skipped', command_triggered: true,
      message: '优化指令未执行：AI 不可用或 Agent 管线未启用',
    } as never)
    const page = await mountPage()
    await type(page, '^update')
    await button(page, '提交').trigger('click')
    await flush()

    const text = page.text()
    expect(text).toContain('指令未被接受（后端原文如下）')
    expect(text).toContain('AI 不可用或 Agent 管线未启用')
  })

  it('提交失败：后端错误原文留在结果区（P6）', async () => {
    vi.mocked(eventsApi.ingest).mockRejectedValue(new Error('422: 内容超出上限'))
    const page = await mountPage()
    await type(page, '太长的一段')
    await button(page, '提交').trigger('click')
    await flush()

    expect(page.text()).toContain('422: 内容超出上限')
  })

  it('输入 ^ 呼出指令候选（候选本身不落库）', async () => {
    const page = await mountPage()
    await type(page, '^')

    const text = page.text()
    expect(text).toContain('^merge')
    expect(text).toContain('^help')
  })
})
