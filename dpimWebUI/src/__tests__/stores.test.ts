import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/repos', () => ({
  listRepos: vi.fn(),
  activateRepo: vi.fn(),
  selectableRepos: (repos: any[]) => repos.filter((r: any) => r.managed && r.loaded),
}))

vi.mock('@/api/health', () => ({
  getStateHash: vi.fn(),
  getHealth: vi.fn(),
}))

import * as repoApi from '@/api/repos'
import * as healthApi from '@/api/health'
import { SCOPE_STORAGE_KEY, useRepoStore } from '@/stores/repo'
import { useSessionStore } from '@/stores/session'
import { useThemeStore } from '@/stores/theme'

function repo(over: Record<string, unknown> = {}) {
  return {
    repo_id: 'rp_a',
    name: '书目甲',
    note: '',
    group: null,
    root_kind: 'managed',
    managed: true,
    active: false,
    loaded: true,
    total_events: 1,
    total_nodes: 2,
    db_path: 'a/memory.db',
    json_path: 'a/graph.json',
    created_at: '',
    updated_at: '',
    ...over,
  } as any
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
})

describe('repo store（书目作用域 = 勾选集合）', () => {
  it('load 后勾选集合默认跟随活动书目（勾 1 本 = 单库，读请求带 repo_id）', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repo({ repo_id: 'rp_a', active: true }), repo({ repo_id: 'rp_b', name: '书目乙' })],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    expect(store.selectedIds).toEqual(['rp_a'])
    expect(store.activeRepoId).toBe('rp_a')
    expect(store.isJoint).toBe(false)
    expect(store.effectiveRepoId).toBe('rp_a')
    expect(store.repoParams()).toEqual({ repo_id: 'rp_a' })
  })

  it('勾 ≥2 本 = 子集联查：repo_ids 按登记表顺序归一，休眠/未加载的库被剔除', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [
        repo({ repo_id: 'rp_a', active: true }),
        repo({ repo_id: 'rp_b' }),
        repo({ repo_id: 'rp_c', managed: false }), // 休眠库不能进联查（后端 422）
        repo({ repo_id: 'rp_d', loaded: false }), // 未加载库同上
      ],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    // 勾选顺序故意打乱：结果必须是登记表顺序（同一集合产出同一参数）
    expect(store.setSelection(['rp_b', 'rp_a'])).toBe(true)
    expect(store.selectedIds).toEqual(['rp_a', 'rp_b'])
    expect(store.isJoint).toBe(true)
    expect(store.effectiveRepoId).toBe('')
    expect(store.repoParams()).toEqual({ repo_ids: ['rp_a', 'rp_b'] })
    expect(store.scopeKey).toBe('rp_a,rp_b')
    // 全部不可用 → 拒绝（不产生「0 个库」或打不通的集合）
    expect(store.setSelection(['rp_c', 'rp_d'])).toBe(false)
    expect(store.selectedIds).toEqual(['rp_a', 'rp_b'])
  })

  it('至少勾一本：取消最后一个被拒绝，保持原选中', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repo({ repo_id: 'rp_a', active: true })],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    expect(store.setSelection([])).toBe(false)
    expect(store.selectedIds).toEqual(['rp_a'])
  })

  it('全选 / 清空（清空 = 至少留一本，回落活动书目）', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [
        repo({ repo_id: 'rp_a' }),
        repo({ repo_id: 'rp_b', active: true }),
        repo({ repo_id: 'rp_c', managed: false }),
      ],
      active_repo_id: 'rp_b',
    })
    const store = useRepoStore()
    await store.load()
    store.selectAll()
    expect(store.selectedIds).toEqual(['rp_a', 'rp_b'])
    expect(store.isJoint).toBe(true)
    expect(store.clearToFallback()).toBe(true)
    expect(store.selectedIds).toEqual(['rp_b']) // 活动书目
    expect(store.isJoint).toBe(false)
  })

  it('勾选集合持久化：写 localStorage，刷新（新一轮 store）后保持', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repo({ repo_id: 'rp_a', active: true }), repo({ repo_id: 'rp_b' })],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    store.setSelection(['rp_a', 'rp_b'])
    expect(JSON.parse(localStorage.getItem(SCOPE_STORAGE_KEY) || '[]')).toEqual(['rp_a', 'rp_b'])

    // 模拟刷新：同一持久化内容 + 新的 pinia
    setActivePinia(createPinia())
    const again = useRepoStore()
    await again.load()
    expect(again.selectedIds).toEqual(['rp_a', 'rp_b'])
    expect(again.repoParams()).toEqual({ repo_ids: ['rp_a', 'rp_b'] })
  })

  it('持久化的库已不存在 → 回退活动书目 + 一次可见提示', async () => {
    localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(['rp_gone', 'rp_b']))
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repo({ repo_id: 'rp_a', active: true }), repo({ repo_id: 'rp_b' })],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    // 还在的库保留，消失的库剔出并提示
    expect(store.selectedIds).toEqual(['rp_b'])
    expect(store.scopeNotice).toContain('已从书目作用域移除')
    store.clearScopeNotice()
    expect(store.scopeNotice).toBe('')

    // 全部失效 → 回退活动书目
    localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(['rp_gone']))
    setActivePinia(createPinia())
    const again = useRepoStore()
    await again.load()
    expect(again.selectedIds).toEqual(['rp_a'])
    expect(again.scopeNotice).toContain('已回退到活动书目')
  })

  it('某本书目被摘除/卸载后，下一次 load 把它从勾选集合里剔掉并提示（不静默留死路）', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repo({ repo_id: 'rp_a', active: true }), repo({ repo_id: 'rp_b' })],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    store.setSelection(['rp_a', 'rp_b'])

    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [repo({ repo_id: 'rp_a', active: true }), repo({ repo_id: 'rp_b', managed: false })],
      active_repo_id: 'rp_a',
    })
    await store.load()
    expect(store.selectedIds).toEqual(['rp_a'])
    expect(store.scopeNotice).toContain('已从书目作用域移除')
  })

  it('groups 按书架分组且未分组排最后', async () => {
    vi.mocked(repoApi.listRepos).mockResolvedValue({
      repos: [
        repo({ repo_id: 'rp_a', group: null }),
        repo({ repo_id: 'rp_b', group: '工作' }),
        repo({ repo_id: 'rp_c', group: '生活' }),
      ],
      active_repo_id: 'rp_a',
    })
    const store = useRepoStore()
    await store.load()
    expect(store.groups.map((g) => g.name)).toEqual(['工作', '生活', '未分组'])
  })

  it('登记表读取失败时记录错误且不把 loaded 置真（P6 失败可见）', async () => {
    vi.mocked(repoApi.listRepos).mockRejectedValue(new Error('坏索引'))
    const store = useRepoStore()
    await store.load()
    expect(store.error).toBe('坏索引')
    expect(store.loaded).toBe(false)
  })
})

describe('session store', () => {
  it('validate 更新密钥；失败时抛错且不改动现有密钥', async () => {
    vi.mocked(healthApi.getStateHash).mockResolvedValue({ hash: 'k1', changed_at: '' } as any)
    const store = useSessionStore()
    await store.validate()
    expect(store.stateKey).toBe('k1')

    vi.mocked(healthApi.getStateHash).mockRejectedValue(new Error('offline'))
    await expect(store.validate()).rejects.toThrow('offline')
    expect(store.stateKey).toBe('k1') // 失败不刷新（密钥非状态派生值）
  })

  it('commit 递增 revision 并刷新密钥；密钥刷新失败不向调用方抛错', async () => {
    const store = useSessionStore()
    vi.mocked(healthApi.getStateHash).mockResolvedValue({ hash: 'k1', changed_at: '' } as any)
    await store.validate()
    const before = store.revision

    vi.mocked(healthApi.getStateHash).mockRejectedValue(new Error('offline'))
    await expect(store.commit()).resolves.toBeUndefined()
    expect(store.revision).toBe(before + 1)
  })
})

describe('theme store', () => {
  it('默认暗色并同步 DOM；切换后写 localStorage 且翻转 DOM', async () => {
    const store = useThemeStore()
    expect(store.mode).toBe('dark')
    await nextTick()
    expect(document.documentElement.dataset.dpimMode).toBe('dark')

    store.toggle()
    expect(store.mode).toBe('light')
    await nextTick() // watcher 在调度队列里刷新 DOM，需等一拍
    expect(document.documentElement.dataset.dpimMode).toBe('light')
    expect(localStorage.getItem('dpim_theme')).toBe('light')
    expect(store.naiveTheme).toBeTruthy()
    expect(store.themeOverrides.common?.primaryColor).toBe('#2f6fb5')
  })

  it('读取已存偏好', () => {
    localStorage.setItem('dpim_theme', 'light')
    const store = useThemeStore()
    expect(store.mode).toBe('light')
    expect(store.isDark).toBe(false)
  })
})
