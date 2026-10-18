/**
 * 概览台（OverviewPage）页面级单测 —— 链 AE（§十 遗留待办 #5：剩余页面级单测）。
 *
 * 本页的价值全在「P1 可见性」：容量 / 备份份数 / 队列 / 降级原因 / 状态密钥都要有落脚处。
 * 这组用例**顺手抓出一个真缺陷**：页面读的是 `eventLine.status_linked` / `status_failed` /
 * `status_raw` / `status_skipped`，而 `/health` 下发的键是 `linked` / `failed` / `raw` /
 * `skipped` → 四个分项**恒显示「—」**（看起来像"没有数据"）。已修，并由第 1 个用例守住。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/health', () => ({
  getHealth: vi.fn(),
  getStateHash: vi.fn(),
  getAgentLogs: vi.fn(),
  compensate: vi.fn(),
  maintain: vi.fn(),
}))
vi.mock('@/api/repos', () => ({
  listRepos: vi.fn(),
  selectableRepos: (repos: any[]) => repos.filter((r: any) => r.managed && r.loaded),
}))

import * as healthApi from '@/api/health'
import * as reposApi from '@/api/repos'
import OverviewPage from '@/pages/OverviewPage.vue'

const Blank = defineComponent({ template: '<div />' })
type Page = ReturnType<typeof mount>

function healthFixture(over: Record<string, unknown> = {}) {
  return {
    status: 'unconfigured',
    ai_available: false,
    ai_unavailable_reason: '未配置任何 AI 提供商（无 AI 模式：存储、检索与指令照常可用）',
    layers: {
      event_line: { total_events: 10, raw: 0, indexed: 0, linked: 10, failed: 0, skipped: 0 },
      knowledge_graph: { total_nodes: 66, system: 1, interaction: 1, data: 49 },
    },
    last_event_at: '2026-08-21T02:36:00+00:00',
    version: '0.4.0',
    queue_depth: 2,
    worker_running: true,
    active_repo_id: 'rp_default',
    storage: { db_bytes: 917504, wal_bytes: 1536, json_bytes: 67967, backups: 3, graph_ops: 0 },
    ...over,
  } as never
}

function repoFixture() {
  return {
    repos: [
      {
        repo_id: 'rp_default', name: '默认库', group: '', root_kind: 'external',
        managed: true, active: true, loaded: true, total_events: 10, total_nodes: 66,
      },
      {
        repo_id: 'rp_b', name: '第二本', group: '工作', root_kind: 'managed',
        managed: true, active: false, loaded: true, total_events: 0, total_nodes: 0,
      },
      {
        repo_id: 'rp_c', name: '休眠本', group: '', root_kind: 'managed',
        managed: false, active: false, loaded: false, total_events: null, total_nodes: null,
      },
    ],
    active_repo_id: 'rp_default',
  } as never
}

async function flush(): Promise<void> {
  await flushPromises()
  await flushPromises()
}

async function mountPage(): Promise<Page> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/overview', name: 'overview', component: Blank }],
  })
  await router.push('/overview')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(OverviewPage) }),
  })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  await flush()
  return wrapper
}

/** 「刷新」= 一次性拉 书目 + 健康 + 状态密钥（本页没有 onMounted，全靠这个按钮） */
async function refresh(page: Page): Promise<void> {
  const btn = page.findAll('button').find((b) => b.text() === '刷新')
  if (!btn) throw new Error('未找到「刷新」按钮')
  await btn.trigger('click')
  await flush()
}

function tile(page: Page, label: string): DOMWrapper<Element> {
  const hit = page.findAll('.tile').find((t) => t.find('.tile-label').text() === label)
  if (!hit) {
    const known = page.findAll('.tile').map((t) => t.find('.tile-label').text()).join(' / ')
    throw new Error(`未找到指标块「${label}」；现有：${known}`)
  }
  return hit
}

function tileValue(page: Page, label: string): string {
  return tile(page, label).find('.tile-value').text()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(healthApi.getHealth).mockResolvedValue(healthFixture())
  vi.mocked(reposApi.listRepos).mockResolvedValue(repoFixture())
  vi.mocked(healthApi.getStateHash).mockResolvedValue({ hash: 'KEY-1', changed_at: '' } as never)
})

describe('OverviewPage（概览台）', () => {
  it('刷新后双区统计显示真实数字（回归：曾读错键 → 四个分项恒为「—」）', async () => {
    const page = await mountPage()
    await refresh(page)

    expect(tileValue(page, '事件总数（原文）')).toBe('10')
    expect(tileValue(page, '知识节点（衍生）')).toBe('66')
    // 这三个此前恒为「—」（键名写成了 status_*）
    expect(tileValue(page, '已入图事件')).toBe('10')
    expect(tileValue(page, '失败事件')).toBe('0')
    expect(tileValue(page, '待处理（raw）')).toBe('0')
    expect(tileValue(page, '已跳过（skipped）')).toBe('0')
  })

  it('书目块：活动书目 / 总数 / 受管已加载（休眠本单独提示）', async () => {
    const page = await mountPage()
    await refresh(page)

    expect(tileValue(page, '当前书目')).toContain('默认库')
    expect(tile(page, '当前书目').text()).toContain('书架')
    expect(tileValue(page, '书目总数')).toBe('3本')
    expect(tileValue(page, '受管 · 已加载')).toBe('2本')
    expect(tile(page, '受管 · 已加载').text()).toContain('休眠/未加载 1 本')
    expect(tileValue(page, '后端版本')).toBe('0.4.0')
  })

  it('容量与保障：体积按量级格式化，备份份数与队列深度可见', async () => {
    const page = await mountPage()
    await refresh(page)

    expect(tileValue(page, '主库体积')).toBe('896.0 KiB')
    expect(tileValue(page, 'WAL 体积')).toBe('1.5 KiB')
    expect(tileValue(page, '图层文件')).toBe('66.4 KiB')
    expect(tileValue(page, '备份份数')).toBe('3')
    expect(tileValue(page, '图层操作日志')).toBe('0条')
    expect(tileValue(page, '队列深度')).toBe('2')
    expect(tile(page, '队列深度').text()).toContain('worker 运行中')
  })

  it('运行状态：AI 三态文案 + 原因、状态校验密钥、连接态', async () => {
    const page = await mountPage()
    await refresh(page)
    const text = page.text()

    expect(text).toContain('未配置 AI · 纯存储可用')
    expect(text).toContain('未配置任何 AI 提供商')
    expect(text).toContain('KEY-1')
    expect(text).toContain('已连接')
    expect(text).toContain('上次检查')
  })

  it('后端不可达：整页降级为「连接不上 + 地址 + 重试」，错误原文常驻', async () => {
    vi.mocked(healthApi.getHealth).mockRejectedValue(new Error('Failed to fetch'))
    const page = await mountPage()
    await refresh(page)
    const text = page.text()

    expect(text).toContain('连接不上后端')
    expect(text).toContain('Failed to fetch')
    expect(text).toContain('重试')
    // 离线时不留空白：指标块整体不渲染
    expect(page.findAll('.tile')).toHaveLength(0)
  })
})
