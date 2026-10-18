/**
 * 备份与恢复（BackupPage）页面级单测 —— 链 AE（§十 遗留待办 #5：剩余页面级单测）。
 *
 * 守住四件事：
 * ① 进页取清单（带库作用域），把时间戳/体积/清单摘要/路径显示出来；
 * ② **恢复指引必须可执行**：示例命令要带最新一份备份的 stamp，且按备份路径反推出库目录
 *    （本地 CLI 没有 --repo，只能靠 DPIM_MEMORY_DB_PATH / DPIM_GRAPH_JSON_PATH 定位）；
 * ③ 新建备份走弹窗（备注 → 开始备份），成功后「最近一次备份」回报 stamp/目录/裁剪份数；
 * ④ 清单读取失败时不动已有清单（旧数据仍可查看）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/maintenance', () => ({
  listBackups: vi.fn(),
  createBackup: vi.fn(),
  verifyStorage: vi.fn(),
  listOps: vi.fn(),
  checkpoint: vi.fn(),
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
import BackupPage from '@/pages/BackupPage.vue'
import { useRepoStore } from '@/stores/repo'

const Blank = defineComponent({ template: '<div />' })
type Page = ReturnType<typeof mount>

function backupRow(over: Record<string, unknown> = {}) {
  return {
    stamp: '20261017-090000',
    path: 'D:/dpim/data/backups/20261017-090000',
    bytes: 917504,
    manifest: {
      total_events: 10, total_nodes: 66, graph_ops: 0,
      schema_version: 3, graph_format_version: 1, note: '改分组前',
    },
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
    routes: [{ path: '/backup', name: 'backup', component: Blank }],
  })
  await router.push('/backup')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(BackupPage) }),
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

function clickModalButton(text: string): void {
  const btns = Array.from(document.querySelectorAll('.modal-actions button'))
  const hit = btns.find((b) => (b.textContent ?? '').trim() === text) as HTMLElement | undefined
  if (!hit) {
    throw new Error(`弹窗里未找到按钮「${text}」；现有：${btns.map((b) => b.textContent?.trim()).join(' / ')}`)
  }
  hit.click()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(maintenanceApi.listBackups).mockResolvedValue({
    backups: [backupRow(), backupRow({ stamp: '20261016-090000', bytes: 1024,
                                      path: 'D:/dpim/data/backups/20261016-090000',
                                      manifest: {} })],
  } as never)
  vi.mocked(maintenanceApi.createBackup).mockResolvedValue({
    stamp: '20261017-120000',
    backup_dir: 'D:/dpim/data/backups/20261017-120000',
    pruned: 1,
    manifest: { total_events: 10, total_nodes: 66 },
  } as never)
  vi.mocked(healthApi.getStateHash).mockResolvedValue({ hash: 'K2', changed_at: '' } as never)
})

describe('BackupPage（备份与恢复）', () => {
  it('进页取清单并显示时间/体积/清单摘要/路径（摘不到清单就退回条目数）', async () => {
    const page = await mountPage()

    expect(maintenanceApi.listBackups).toHaveBeenCalledTimes(1)
    const text = page.text()
    expect(text).toContain('20261017-090000')
    expect(text).toContain('896.0 KiB')
    expect(text).toContain('事件 10 · 节点 66 · 操作日志 0 · 存储版本 3 · 图层版本 1')
    expect(text).toContain('备注「改分组前」')
    expect(text).toContain('D:/dpim/data/backups/20261017-090000')
    expect(text).toContain('无清单') // 第二份 manifest 为空
    expect(text).toContain('备份按份数保留（最近 5 份）')
  })

  it('恢复指引可执行：示例命令带最新 stamp，并按备份路径反推库目录', async () => {
    const page = await mountPage()
    const text = page.text()

    expect(text).toContain('恢复（须停服务 · 本地 CLI）')
    expect(text).toContain('python main.py restore')
    expect(text).toContain('python main.py restore 20261017-090000 --yes')
    // 本地 CLI 没有 --repo：必须把两个环境变量指到该库
    expect(text).toContain('DPIM_MEMORY_DB_PATH=D:/dpim/data/memory.db')
    expect(text).toContain('DPIM_GRAPH_JSON_PATH=D:/dpim/data/graph.json')
    expect(text).toContain('本页刻意不提供在线恢复按钮')
  })

  it('新建备份：弹窗填备注 → 开始备份 → 回报 stamp/目录/裁剪份数', async () => {
    const page = await mountPage()

    await button(page, '新建备份').trigger('click')
    await flush()
    expect(document.querySelector('.modal-box')?.textContent).toContain('新建备份')

    const input = document.querySelector('.modal-box input') as HTMLInputElement
    input.value = '改分组前的备份'
    input.dispatchEvent(new Event('input'))
    await flush()

    clickModalButton('开始备份')
    await flush()

    expect(vi.mocked(maintenanceApi.createBackup).mock.calls[0]).toEqual([
      '改分组前的备份', undefined,
    ])
    const text = page.text()
    expect(text).toContain('最近一次备份')
    expect(text).toContain('20261017-120000')
    expect(text).toContain('D:/dpim/data/backups/20261017-120000')
    expect(text).toContain('1 份')
  })

  it('新建备份失败：后端原文常驻「新建备份失败」卡片（弹窗里也有一份）', async () => {
    vi.mocked(maintenanceApi.createBackup).mockRejectedValue(
      new Error('409: 内存库不支持备份（请用真实文件库）'),
    )
    const page = await mountPage()
    await button(page, '新建备份').trigger('click')
    await flush()
    clickModalButton('开始备份')
    await flush()

    expect(page.text()).toContain('新建备份失败')
    expect(page.text()).toContain('409: 内存库不支持备份')
  })

  it('库作用域：跟随顶栏勾选（勾 1 本时带 repo_id）', async () => {
    const repo = useRepoStore()
    repo.repos = [
      { repo_id: 'rp_a', name: '甲', managed: true, loaded: true, active: true, root_kind: 'managed' },
      { repo_id: 'rp_b', name: '乙', managed: true, loaded: true, active: false, root_kind: 'managed' },
    ] as never
    repo.setSelection(['rp_b'])
    await mountPage()

    expect(vi.mocked(maintenanceApi.listBackups).mock.calls[0][0]).toBe('rp_b')
  })

  it('联查（勾选 ≥2 本）：清单逐库汇总并注明「来自书目」；新建备份是写动作，只打活动书目', async () => {
    vi.mocked(maintenanceApi.listBackups).mockImplementation(((repoId?: string) =>
      Promise.resolve({
        backups: [
          backupRow({
            stamp: '20261017-090000',
            path: `D:/dpim/${repoId}/backups/20261017-090000`,
          }),
        ],
      })) as never)
    const repo = useRepoStore()
    repo.repos = [
      { repo_id: 'rp_a', name: '甲', managed: true, loaded: true, active: true, root_kind: 'managed' },
      { repo_id: 'rp_b', name: '乙', managed: true, loaded: true, active: false, root_kind: 'managed' },
    ] as never
    repo.setSelection(['rp_a', 'rp_b'])
    const page = await mountPage()

    expect(vi.mocked(maintenanceApi.listBackups).mock.calls.map((c) => c[0])).toEqual([
      'rp_a',
      'rp_b',
    ])
    const text = page.text()
    expect(text).toContain('来自书目')
    expect(text).toContain('只作用于活动书目《甲》')
    // 恢复指引按**写目标那一本**（活动书目）反推库目录，不拿汇总里的第一行冒充
    expect(text).toContain('DPIM_MEMORY_DB_PATH=D:/dpim/rp_a/memory.db')

    await button(page, '新建备份').trigger('click')
    await flush()
    clickModalButton('开始备份')
    await flush()

    expect(vi.mocked(maintenanceApi.createBackup).mock.calls[0]).toEqual(['', 'rp_a'])
  })

  it('清单读取失败：不动已有清单，给出横幅与重试', async () => {
    const page = await mountPage()
    expect(page.text()).toContain('20261017-090000')

    vi.mocked(maintenanceApi.listBackups).mockRejectedValue(new Error('503: Storage not initialized'))
    await button(page, '刷新').trigger('click')
    await flush()

    const text = page.text()
    expect(text).toContain('备份清单读取失败')
    expect(text).toContain('503: Storage not initialized')
    expect(text).toContain('20261017-090000')
  })

  it('空清单：给出「还没有备份」与「备份是恢复的唯一退路」', async () => {
    vi.mocked(maintenanceApi.listBackups).mockResolvedValue({ backups: [] } as never)
    const page = await mountPage()

    const text = page.text()
    expect(text).toContain('这本书目还没有备份')
    expect(text).toContain('备份是恢复的唯一退路')
  })
})
