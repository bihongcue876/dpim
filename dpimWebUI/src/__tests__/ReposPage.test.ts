import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h, nextTick } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/repos', () => ({
  listRepos: vi.fn(),
  createRepo: vi.fn(),
  updateRepo: vi.fn(),
  deleteRepo: vi.fn(),
  activateRepo: vi.fn(),
  refreshRepo: vi.fn(),
  generateRepo: vi.fn(),
  rebuildRepos: vi.fn(),
  purgeRepo: vi.fn(),
  adoptRepo: vi.fn(),
  selectableRepos: (repos: any[]) => repos.filter((r: any) => r.managed && r.loaded),
}))
vi.mock('@/api/health', () => ({
  getHealth: vi.fn(),
  getStateHash: vi.fn(),
}))

import * as reposApi from '@/api/repos'
import * as healthApi from '@/api/health'
import ReposPage from '@/pages/ReposPage.vue'
import { useRepoStore } from '@/stores/repo'

const Blank = defineComponent({ template: '<div />' })

function repoRow(over: Record<string, unknown> = {}) {
  return {
    repo_id: 'rp_a',
    name: '书目甲',
    note: '地方志摘录',
    group: '工作',
    root_kind: 'managed',
    managed: true,
    active: false,
    loaded: true,
    total_events: 12,
    total_nodes: 34,
    db_path: 'D:/data/repos/工作/rp_a/memory.db',
    json_path: 'D:/data/repos/工作/rp_a/graph.json',
    created_at: '',
    updated_at: '',
    ...over,
  } as any
}

const MODAL_STUB = { template: '<div class="stub-modal"><slot /></div>' }

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/repos', name: 'repos', component: Blank }],
  })
  await router.push('/repos')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(ReposPage) }),
  })
  const wrapper = mount(Host, {
    global: { plugins: [router], stubs: { NModal: MODAL_STUB } },
  })
  await nextTick()
  await new Promise((r) => setTimeout(r, 0))
  await nextTick()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = '' // 清掉上一用例 teleport 出去的弹窗
  vi.mocked(healthApi.getStateHash).mockResolvedValue({ hash: 'k', changed_at: '' } as never)
})

describe('ReposPage（书目管理）', () => {
  it('卡片显示备注、db/json 两个路径、类型与计数（此前这些都看不到）', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow()],
      active_repo_id: 'rp_a',
    })
    const wrapper = await mountPage()
    const text = wrapper.text()
    expect(text).toContain('地方志摘录')
    expect(text).toContain('D:/data/repos/工作/rp_a/memory.db')
    expect(text).toContain('D:/data/repos/工作/rp_a/graph.json')
    expect(text).toContain('托管')
    expect(text).toContain('12 / 34')
    expect(text).toContain('书架 · 工作')
  })

  it('备注为空时给出「（无备注）」而不是空白', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow({ note: '' })],
      active_repo_id: 'rp_a',
    })
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('（无备注）')
  })

  it('默认书目的摘除 / 删除文件按钮禁用，且卡片上写明原因（修掉「点了没反应」）', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow({ repo_id: 'rp_default', name: '默认书目' })],
      active_repo_id: 'rp_default',
    })
    const wrapper = await mountPage()
    const buttons = wrapper.findAll('button')
    const remove = buttons.find((b) => b.text() === '摘除登记')!
    const purge = buttons.find((b) => b.text() === '删除书目及其文件')!
    expect(remove.attributes('disabled')).toBeDefined()
    expect(purge.attributes('disabled')).toBeDefined()
    const reason = wrapper.find('.block-reason')
    expect(reason.exists()).toBe(true)
    expect(reason.text()).toContain('默认书目')
  })

  it('活动书目（非默认）同样禁用并提示先切换活动书目', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow({ repo_id: 'rp_b', name: '乙', active: true })],
      active_repo_id: 'rp_b',
    })
    const wrapper = await mountPage()
    const purge = wrapper.findAll('button').find((b) => b.text() === '删除书目及其文件')!
    expect(purge.attributes('disabled')).toBeDefined()
    expect(wrapper.find('.block-reason').text()).toContain('活动书目')
  })

  it('登记表读取失败时把后端原文与「重建登记表」出口一起显示（P6）', async () => {
    vi.mocked(reposApi.listRepos).mockRejectedValue(new Error('repos/index.json 解析失败'))
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('书目登记表读取失败')
    expect(wrapper.text()).toContain('repos/index.json 解析失败')
    expect(wrapper.findAll('button').some((b) => b.text() === '重建登记表')).toBe(true)
  })

  it('重建登记表走二次确认，并说明「不删除任何磁盘数据文件」', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow({ repo_id: 'rp_default', name: '默认书目' })],
      active_repo_id: 'rp_default',
    })
    const wrapper = await mountPage()
    const rebuild = wrapper.findAll('button').find((b) => b.text() === '重建登记表')!
    await rebuild.trigger('click')
    await nextTick()
    await nextTick()
    expect(reposApi.rebuildRepos).not.toHaveBeenCalled()
    // ConfirmDialog 的 n-modal teleport 到 body，故断言走 document
    expect(document.body.textContent).toContain('重建书目登记表？')
    expect(document.body.textContent).toContain('不会删除任何磁盘数据文件')
  })

  it('收养目录：入口在工具条，弹窗写明「只补空件」与 graph_ops 重放', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow({ repo_id: 'rp_b', name: '乙', active: false })],
      active_repo_id: 'rp_a',
    })
    const wrapper = await mountPage()
    const adopt = wrapper.findAll('button').find((b) => b.text() === '收养目录')
    expect(adopt).toBeTruthy()
    await adopt!.trigger('click')
    await nextTick()
    await nextTick()

    const text = document.body.textContent || ''
    expect(text).toContain('只补空件')
    expect(text).toContain('graph_ops')
    // 至少要有其中一个库文件才叫「收养」；一个都没有属于「新建」
    expect(text).toContain('新建')
  })

  it('未加载的书目若后端给出 load_error，卡片上要显示原因（不编造）', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [
        repoRow({
          repo_id: 'rp_c',
          name: '丙',
          loaded: false,
          total_events: null,
          load_error: '登记文件缺失：graph.json（库目录 D:/data/repos/未分组/rp_c）',
        }),
      ],
      active_repo_id: 'rp_a',
    })
    const wrapper = await mountPage()
    const err = wrapper.find('.load-error')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('graph.json')
  })

  it('删除书目及其文件：二次确认后调 purge，并把备份路径显示出来', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow({ repo_id: 'rp_b', name: '乙', active: false })],
      active_repo_id: 'rp_a',
    })
    vi.mocked(reposApi.purgeRepo).mockResolvedValue({
      message: '已删除书目及其文件',
      backup_path: 'D:/data/backups/20261004-120000',
    } as never)

    const wrapper = await mountPage()
    const purge = wrapper.findAll('button').find((b) => b.text() === '删除书目及其文件')!
    await purge.trigger('click')
    await nextTick()
    await nextTick()
    expect(reposApi.purgeRepo).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('删除书目及其文件？（不可逆）')

    const confirmBtn = [...document.querySelectorAll('button')].find(
      (b) => b.textContent?.trim() === '删除文件',
    ) as HTMLButtonElement
    expect(confirmBtn).toBeTruthy()
    confirmBtn.click()
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()

    expect(reposApi.purgeRepo).toHaveBeenCalledWith('rp_b')
    expect(wrapper.text()).toContain('D:/data/backups/20261004-120000')
  })

  it('设为活动书目：未加载的受管库按钮禁用并说明先「刷新修复」', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow({ repo_id: 'rp_c', name: '丙', loaded: false, total_events: null })],
      active_repo_id: 'rp_a',
    })
    const wrapper = await mountPage()
    const activate = wrapper.findAll('button').find((b) => b.text() === '设为活动书目')!
    expect(activate.attributes('disabled')).toBeDefined()
    expect(wrapper.find('.state-note').text()).toContain('未加载')
    expect(wrapper.text()).toContain('未加载')
  })

  it('空清单给出「后端会把现有数据登记为默认书目」的引导，而不是空白页', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({ repos: [], active_repo_id: '' })
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('尚无书目')
    expect(wrapper.text()).toContain('默认书目')
  })

  it('store 已加载时页面不再重复拉取（复用全局书目清单）', async () => {
    vi.mocked(reposApi.listRepos).mockResolvedValue({
      repos: [repoRow()],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    const callsAfterStore = vi.mocked(reposApi.listRepos).mock.calls.length
    await mountPage()
    // 页面 onMounted 会再拉一次用于「刷新」语义，但不应出现 N 次（每个卡片一次）
    expect(vi.mocked(reposApi.listRepos).mock.calls.length).toBeLessThanOrEqual(callsAfterStore + 1)
  })
})
