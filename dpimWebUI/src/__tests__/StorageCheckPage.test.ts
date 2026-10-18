/**
 * 存储体检（StorageCheckPage）页面级单测 —— 链 AE（§十 遗留待办 #5：剩余页面级单测）。
 *
 * 守住五件事：
 * ① 进页先取操作日志 + 健康（校验要手动点，避免每次进页都跑一遍重校验）；
 * ② 校验结论**如实**：未通过时给出「N / M 项未通过」，并把 check 名翻成中文、细节原文可见；
 * ③ 全通过时给「存储层当前可信任」的正向结论；
 * ④ 校验接口失败不静默降级：错误原文常驻 + 重试；
 * ⑤ 联查（勾选 ≥2 本）时校验与操作日志**逐库**汇总，且维护动作明说只作用于活动书目（不许悄悄打错库）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/maintenance', () => ({
  verify: vi.fn(),
  listOps: vi.fn(),
  listBackups: vi.fn(),
  createBackup: vi.fn(),
  checkpoint: vi.fn(),
}))
vi.mock('@/api/repos', () => ({
  listRepos: vi.fn(),
  refreshRepo: vi.fn(),
  selectableRepos: (repos: any[]) => repos.filter((r: any) => r.managed && r.loaded),
}))
vi.mock('@/api/health', () => ({
  getHealth: vi.fn(),
  getStateHash: vi.fn(),
  getAgentLogs: vi.fn(),
  compensate: vi.fn(),
  maintain: vi.fn(),
}))

import * as maintenanceApi from '@/api/maintenance'
import * as healthApi from '@/api/health'
import StorageCheckPage from '@/pages/StorageCheckPage.vue'
import { useRepoStore } from '@/stores/repo'

const Blank = defineComponent({ template: '<div />' })
type Page = ReturnType<typeof mount>

const FAILING_CHECKS = [
  { name: 'sqlite_integrity', ok: true, detail: 'ok' },
  { name: 'foreign_keys', ok: true, detail: '0 条违规' },
  { name: 'events_fts_consistency', ok: true, detail: 'events=10 events_fts=10' },
  { name: 'node_fts_consistency', ok: false, detail: 'nodes=66 node_fts=51' },
  { name: 'ops_replay_matches_graph', ok: false, detail: 'ops=0 重放 nodes=0/live=51' },
  { name: 'no_dangling_source_refs', ok: true, detail: '悬空 0 条' },
  { name: 'no_dateless_nodes', ok: false, detail: "15 个节点缺 data（如 ['bbf250c0…']）" },
]

function verifyFixture(ok: boolean) {
  return {
    ok,
    checks: ok ? FAILING_CHECKS.map((c) => ({ ...c, ok: true })) : FAILING_CHECKS,
    sizes: { db_bytes: 917504, wal_bytes: 1536, json_bytes: 67967, backups: 0, trash_items: 0 },
    counts: { events: 10, nodes: 66, edges: 56, graph_ops: 0 },
  } as never
}

async function flush(): Promise<void> {
  await flushPromises()
  await flushPromises()
}

async function mountPage(): Promise<Page> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/storage', name: 'storage', component: Blank }],
  })
  await router.push('/storage')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(StorageCheckPage) }),
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

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(healthApi.getHealth).mockResolvedValue({
    status: 'unconfigured', ai_available: false, layers: {}, storage: { db_bytes: 917504 },
  } as never)
  vi.mocked(maintenanceApi.listOps).mockResolvedValue({
    ops: [
      { op_id: 1, created_at: '2026-10-17T02:00:00+00:00', op_kind: 'node_upsert',
        reason: '维护计划: merges=1', actor: 'system', payload: { node: { node_id: 'n1' } } },
    ],
    total: 1,
  } as never)
  vi.mocked(maintenanceApi.verify).mockResolvedValue(verifyFixture(false))
})

describe('StorageCheckPage（存储体检）', () => {
  it('进页取操作日志；校验**不自动跑**（给出「尚未运行校验」引导）', async () => {
    const page = await mountPage()

    expect(maintenanceApi.listOps).toHaveBeenCalledTimes(1)
    expect(maintenanceApi.verify).not.toHaveBeenCalled()
    expect(page.text()).toContain('尚未运行校验')
    // 健康由顶栏/外壳统一刷新，本页只在「刷新」「刷新修复」后顺带刷一次
    expect(healthApi.getHealth).not.toHaveBeenCalled()
  })

  it('校验未通过：如实报「N / M 项未通过」，check 名翻中文、细节原文可见', async () => {
    const page = await mountPage()
    await button(page, '运行校验').trigger('click')
    await flush()

    expect(maintenanceApi.verify).toHaveBeenCalledTimes(1)
    const text = page.text()
    expect(text).toContain('FAIL')
    expect(text).toContain('3 / 7 项未通过')
    expect(text).toContain('节点 ↔ 节点索引行数一致')
    expect(text).toContain('操作日志重放一致性')
    expect(text).toContain('无缺 data 节点')
    expect(text).toContain('nodes=66 node_fts=51')
    expect(text).toContain('15 个节点缺 data')
    expect(text).toContain('3 项未通过 / 共 7 项')
  })

  it('校验全通过：给正向结论「存储层当前可信任」', async () => {
    vi.mocked(maintenanceApi.verify).mockResolvedValue(verifyFixture(true))
    const page = await mountPage()
    await button(page, '运行校验').trigger('click')
    await flush()

    const text = page.text()
    expect(text).toContain('OK')
    expect(text).toContain('全部 7 项通过：存储层当前可信任')
  })

  it('校验接口失败：不静默降级，错误原文常驻并可重试', async () => {
    vi.mocked(maintenanceApi.verify).mockRejectedValue(new Error('503: Storage not initialized'))
    const page = await mountPage()
    await button(page, '运行校验').trigger('click')
    await flush()

    const text = page.text()
    expect(text).toContain('503: Storage not initialized')
    // 失败必须**可见**：点名是哪个库失败 + 明说「没有结论 ≠ 通过」（不静默降级）
    expect(text).toContain('部分书目校验失败')
    expect(text).toContain('不是「通过」')
    expect(text).toContain('刷新一致性校验') // 失败后仍能重跑（重试入口在工具栏）
  })

  it('图层操作日志：显示类型（翻中文）/执行者/原因（谁、因何改了图）', async () => {
    const page = await mountPage()
    await button(page, '运行校验').trigger('click')
    await flush()

    const text = page.text()
    expect(text).toContain('节点写入') // op_kind=node_upsert 的中文标签
    expect(text).toContain('system')
    expect(text).toContain('维护计划: merges=1')
    expect(text).toContain('共 1 条')
  })

  it('容量与计数：体积按量级格式化，计数原样显示', async () => {
    const page = await mountPage()
    await button(page, '运行校验').trigger('click')
    await flush()

    const text = page.text()
    expect(text).toContain('896.0 KiB')
    expect(text).toContain('1.5 KiB')
    expect(text).toContain('66.4 KiB')
  })

  it('联查（勾选 ≥2 本）：校验与操作日志逐库汇总，写动作明说只作用于活动书目《甲》', async () => {
    const repo = useRepoStore()
    repo.repos = [
      { repo_id: 'rp_a', name: '甲', managed: true, loaded: true, active: true, root_kind: 'managed' },
      { repo_id: 'rp_b', name: '乙', managed: true, loaded: true, active: false, root_kind: 'managed' },
    ] as never
    repo.setSelection(['rp_a', 'rp_b'])
    const page = await mountPage()

    // 写动作必须点名目标（不许悄悄打错库）
    expect(page.text()).toContain('只作用于活动书目《甲》')
    // 读路径按勾选集合逐库取（GET /maintenance/ops 只有 repo_id，没有 repo_ids）
    expect(maintenanceApi.listOps).toHaveBeenCalledTimes(2)
    expect(vi.mocked(maintenanceApi.listOps).mock.calls.map((c) => c[0].repo_id)).toEqual([
      'rp_a',
      'rp_b',
    ])

    await button(page, '运行校验').trigger('click')
    await flush()

    expect(maintenanceApi.verify).toHaveBeenCalledTimes(2)
    const text = page.text()
    expect(text).toContain('逐库跑了 2 本')
    expect(text).toContain('来自书目')
    expect(text).toContain('6 / 14 项未通过') // 两本各 7 项，夹具里各 3 项 FAIL → 合计 6
    expect(text).toContain('跨库合计')
  })
})
