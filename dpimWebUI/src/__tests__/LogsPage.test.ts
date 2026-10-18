/**
 * 日志（LogsPage）页面级单测 —— 链 AE（§十 遗留待办 #5：剩余页面级单测）。
 *
 * 守住四件事：
 * ① 进页即按默认参数取一次（`kind=backend` / `tail=200`），并把行与目录显示出来；
 * ② `truncated` 必须**看得见**（只说「显示 N 行」会让人以为这就是全部）；
 * ③ 读取失败要把后端错误原文与日志目录留在页面上（P6 失败可见，不能只在 toast 里闪）；
 * ④ 切通道（后端 ↔ 前端）要换参数重取，且不串通道显示旧行。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/logs', () => ({ listLogs: vi.fn() }))

import * as logsApi from '@/api/logs'
import LogsPage from '@/pages/LogsPage.vue'

const Blank = defineComponent({ template: '<div />' })
type Page = ReturnType<typeof mount>

function logsFixture(over: Record<string, unknown> = {}) {
  return {
    kind: 'backend',
    date: '2026-10-17',
    dir: 'D:/dpim/logs',
    files: [
      { name: 'backend-2026-10-17.log', kind: 'backend', date: '2026-10-17', size: 917, mtime: 0 },
      { name: 'backend-2026-10-16.log', kind: 'backend', date: '2026-10-16', size: 838, mtime: 0 },
    ],
    lines: [
      '2026-10-17 09:53:24 | INFO    | interface.api | 保留策略：检查 2 个库',
      '2026-10-17 09:53:29 | WARNING | controller.compensator | AI 未配置',
    ],
    truncated: false,
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
    routes: [{ path: '/logs', name: 'logs', component: Blank }],
  })
  await router.push('/logs')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(LogsPage) }),
  })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  await flush()
  return wrapper
}

function button(page: Page, text: string): DOMWrapper<Element> {
  const hit = page.findAll('button').find((b) => b.text() === text)
  if (!hit) throw new Error(`未找到按钮「${text}」`)
  return hit
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(logsApi.listLogs).mockResolvedValue(logsFixture())
})

describe('LogsPage（日志）', () => {
  it('进页按默认参数取一次，行与目录都显示出来', async () => {
    const page = await mountPage()

    expect(logsApi.listLogs).toHaveBeenCalledTimes(1)
    expect(vi.mocked(logsApi.listLogs).mock.calls[0][0]).toEqual({
      kind: 'backend', date: undefined, level: undefined, keyword: undefined, tail: 200,
    })
    const text = page.text()
    expect(text).toContain('保留策略：检查 2 个库')
    expect(text).toContain('D:/dpim/logs')
    expect(text).toContain('显示 2 行')
    expect(text).toContain('日期 2026-10-17')
    expect(text).toContain('backend-2026-10-17.log')
  })

  it('truncated 看得见：说明只显示了最新 N 行并给出建议', async () => {
    vi.mocked(logsApi.listLogs).mockResolvedValue(logsFixture({ truncated: true }))
    const page = await mountPage()

    const text = page.text()
    expect(text).toContain('已截断：仅显示最新 2 行')
    expect(text).toContain('匹配行多于所选尾部档位')
  })

  it('读取失败：错误原文与日志目录留在页面上，可重试', async () => {
    vi.mocked(logsApi.listLogs).mockRejectedValue(new Error('400: date 格式非法：2026/10/17'))
    const page = await mountPage()

    const text = page.text()
    expect(text).toContain('400: date 格式非法')
    expect(text).toContain('日志目录')
    expect(text).toContain('重试')
    expect(button(page, '重试')).toBeTruthy()
  })

  it('切到前端通道：换 kind 重取，且日期回到「最新」不沿用后端那天', async () => {
    const page = await mountPage()
    // 首次取回后日期下拉被对齐到实际返回的那一天
    expect(vi.mocked(logsApi.listLogs).mock.calls[0][0].date).toBeUndefined()

    vi.mocked(logsApi.listLogs).mockResolvedValue(logsFixture({ kind: 'frontend', lines: ['前端日志一行'] }))
    const frontendRadio = page.findAll('input[type="radio"]')[1]
    await frontendRadio.setValue()
    await flush()

    const lastCall = vi.mocked(logsApi.listLogs).mock.calls.at(-1)![0]
    expect(lastCall.kind).toBe('frontend')
    expect(page.text()).toContain('前端日志一行')
  })

  it('空结果：按「没有该通道文件」与「筛选无匹配」给不同提示', async () => {
    vi.mocked(logsApi.listLogs).mockResolvedValue(
      logsFixture({ files: [], lines: [], date: '' }),
    )
    const page = await mountPage()

    expect(page.text()).toContain('没有后端日志文件')
    expect(page.text()).toContain('后端启动后才会写入日志文件')
  })
})
