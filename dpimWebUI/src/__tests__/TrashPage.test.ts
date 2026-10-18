/**
 * 回收站（TrashPage）页面级单测 —— 链 AE（§十 遗留待办 #5：剩余页面级单测）。
 *
 * 本页是**破坏性的反面**：恢复会把留档按原 ID 放回库。守住四件事：
 * ① 进页取清单（带库作用域），把留档时间/类型/原 ID/摘要显示出来，目录可见；
 * ② 恢复走二次确认，且确认里写清影响（按原 ID、409 不覆盖、留档移入 restored/）；
 * ③ 恢复失败（如 409 已存在）必须把后端原文常驻在页面上；
 * ④ 清单读取失败时**不动已有清单**（旧数据仍可查看）。
 *
 * 注意：二次确认用 `n-modal`，内容 **teleport 到 document.body**，所以弹窗文本与按钮
 * 要查 `document.body`（`wrapper.text()` 里没有它）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/trash', () => ({
  listTrash: vi.fn(),
  restoreTrash: vi.fn(),
}))

import * as trashApi from '@/api/trash'
import TrashPage from '@/pages/TrashPage.vue'
import { useRepoStore } from '@/stores/repo'

const Blank = defineComponent({ template: '<div />' })
type Page = ReturnType<typeof mount>

function item(over: Record<string, unknown> = {}) {
  return {
    kind: 'event', id: '1787279783926-bc', archived_at: '2026-10-17T02:00:00+00:00',
    size: 512, title: '一段被删掉的原文', path: 'D:/dpim/trash/events/1787279783926-bc.json',
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
    routes: [{ path: '/trash', name: 'trash', component: Blank }],
  })
  await router.push('/trash')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(TrashPage) }),
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

/** 二次确认弹窗（teleport 到 body）的文本 */
function dialogText(): string {
  return document.querySelector('.confirm')?.textContent ?? ''
}

/** 点弹窗里的按钮（表格每行也有个「恢复」，所以必须限定在 `.confirm-actions` 内） */
function clickDialogButton(text: string): void {
  const btns = Array.from(document.querySelectorAll('.confirm-actions button'))
  const hit = btns.find((b) => (b.textContent ?? '').trim() === text) as HTMLElement | undefined
  if (!hit) {
    throw new Error(
      `弹窗里未找到按钮「${text}」；现有：${btns.map((b) => b.textContent?.trim()).join(' / ')}`,
    )
  }
  hit.click()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(trashApi.listTrash).mockResolvedValue({
    items: [item(), item({ kind: 'node', id: 'n_deleted', title: '', size: 256,
                           path: 'D:/dpim/trash/nodes/n_deleted.json' })],
    dir: 'D:/dpim/trash',
  } as never)
  vi.mocked(trashApi.restoreTrash).mockResolvedValue({ message: '已按原 ID 恢复' } as never)
})

describe('TrashPage（回收站）', () => {
  it('进页取清单并显示留档时间/类型/原 ID/摘要与留档目录', async () => {
    const page = await mountPage()

    expect(trashApi.listTrash).toHaveBeenCalledTimes(1)
    const text = page.text()
    expect(text).toContain('事件')
    expect(text).toContain('节点')
    expect(text).toContain('1787279783926-bc')
    expect(text).toContain('一段被删掉的原文')
    expect(text).toContain('（留档无标题/摘要）')
    expect(text).toContain('D:/dpim/trash')
  })

  it('库作用域：跟随顶栏勾选（勾 1 本时带 repo_id）', async () => {
    const repo = useRepoStore()
    repo.repos = [
      { repo_id: 'rp_a', name: '甲', managed: true, loaded: true, active: true, root_kind: 'managed' },
      { repo_id: 'rp_b', name: '乙', managed: true, loaded: true, active: false, root_kind: 'managed' },
    ] as never
    repo.setSelection(['rp_b'])
    await mountPage()

    expect(vi.mocked(trashApi.listTrash).mock.calls[0][0]).toBe('rp_b')
  })

  it('联查（勾选 ≥2 本）：逐库取清单并汇总，注明「来自书目」，恢复按该条所属书目下发 repo_id', async () => {
    vi.mocked(trashApi.listTrash).mockImplementation(((repoId?: string) =>
      Promise.resolve({
        items: [item({ id: `ev_${repoId}`, path: `D:/dpim/${repoId}/trash/events/ev_${repoId}.json` })],
        dir: `D:/dpim/${repoId}/trash`,
      })) as never)
    const repo = useRepoStore()
    repo.repos = [
      { repo_id: 'rp_a', name: '甲', managed: true, loaded: true, active: true, root_kind: 'managed' },
      { repo_id: 'rp_b', name: '乙', managed: true, loaded: true, active: false, root_kind: 'managed' },
    ] as never
    repo.setSelection(['rp_a', 'rp_b'])
    const page = await mountPage()

    expect(vi.mocked(trashApi.listTrash).mock.calls.map((c) => c[0])).toEqual(['rp_a', 'rp_b'])
    const text = page.text()
    expect(text).toContain('来自书目')
    expect(text).toContain('甲')
    expect(text).toContain('乙')
    expect(text).toContain('2 本书目各自的留档目录')

    // 选第二行（乙库的那条）→ 恢复必须打到乙（否则会 404「留档不存在」）
    await page.findAll('tbody tr')[1].trigger('click')
    await flush()
    await button(page, '恢复选中').trigger('click')
    await flush()
    expect(dialogText()).toContain('乙')
    clickDialogButton('恢复')
    await flush()

    expect(vi.mocked(trashApi.restoreTrash).mock.calls[0]).toEqual(['event', 'ev_rp_b', 'rp_b'])
  })

  it('恢复走二次确认：影响说明写清「按原 ID / 409 不覆盖 / 移入 restored」', async () => {
    const page = await mountPage()

    // 点选一行 → 右上角「恢复选中」可用
    await page.findAll('tbody tr')[0].trigger('click')
    await flush()
    expect(page.text()).toContain('已选中：事件 1787279783926-bc')

    await button(page, '恢复选中').trigger('click')
    await flush()

    const text = dialogText()
    expect(text).toContain('按原 ID 恢复这条留档？')
    expect(text).toContain('按**原 ID** 恢复')
    expect(text).toContain('409 并拒绝恢复（不会覆盖现有数据）')
    expect(text).toContain('trash/restored/')
  })

  it('确认后调恢复接口（带库作用域），并把结果留在「上次恢复结果」里', async () => {
    const page = await mountPage()
    await page.findAll('tbody tr')[0].trigger('click')
    await flush()
    await button(page, '恢复选中').trigger('click')
    await flush()

    clickDialogButton('恢复')
    await flush()

    expect(vi.mocked(trashApi.restoreTrash).mock.calls[0]).toEqual([
      'event', '1787279783926-bc', undefined,
    ])
    expect(page.text()).toContain('已按原 ID 恢复')
  })

  it('恢复失败（409 已存在）：后端原文常驻「恢复失败」卡片', async () => {
    vi.mocked(trashApi.restoreTrash).mockRejectedValue(
      new Error('409: 已存在同 ID 的事件，拒绝覆盖'),
    )
    const page = await mountPage()
    await page.findAll('tbody tr')[0].trigger('click')
    await flush()
    await button(page, '恢复选中').trigger('click')
    await flush()
    clickDialogButton('恢复')
    await flush()

    const text = page.text()
    expect(text).toContain('恢复失败')
    expect(text).toContain('409: 已存在同 ID 的事件，拒绝覆盖')
    expect(button(page, '关闭')).toBeTruthy()
  })

  it('清单读取失败：不动已有清单，并给出「留档清单读取失败」横幅与重试', async () => {
    const page = await mountPage()
    expect(page.text()).toContain('1787279783926-bc')

    vi.mocked(trashApi.listTrash).mockRejectedValue(new Error('503: Repos not initialized'))
    await button(page, '刷新').trigger('click')
    await flush()

    const text = page.text()
    expect(text).toContain('留档清单读取失败')
    expect(text).toContain('503: Repos not initialized')
    expect(text).toContain('1787279783926-bc') // 旧清单仍在
  })

  it('空清单：给出「暂无留档」与留档机制说明', async () => {
    vi.mocked(trashApi.listTrash).mockResolvedValue({ items: [], dir: 'D:/dpim/trash' } as never)
    const page = await mountPage()

    const text = page.text()
    expect(text).toContain('暂无留档')
    expect(text).toContain('删除事件或节点、或清空图层时会自动留档到这里')
  })
})

describe('TrashPage 整图留档（v1.42）', () => {
  const GRAPH_ITEM = {
    kind: 'graph', id: 'graph-20261017-144222', archived_at: '2026-10-17T06:42:22+00:00',
    size: 67967, title: '整图留档：51 节点 / 56 边',
    path: 'D:/dpim/trash/graphs/graph-20261017-144222.json',
  }

  beforeEach(() => {
    vi.mocked(trashApi.listTrash).mockResolvedValue({
      items: [item(GRAPH_ITEM)], dir: 'D:/dpim/trash',
    } as never)
  })

  it('清单把第三类显示为「整图」并给出节点/边计数摘要', async () => {
    const page = await mountPage()

    const text = page.text()
    expect(text).toContain('整图')
    expect(text).toContain('整图留档：51 节点 / 56 边')
    expect(text).toContain('graph-20261017-144222')
  })

  it('确认框说明「合并式恢复 / 不覆盖 / 不造悬空边」，且不提 409', async () => {
    const page = await mountPage()
    await page.findAll('tbody tr')[0].trigger('click')
    await flush()
    await button(page, '恢复选中').trigger('click')
    await flush()

    const text = dialogText()
    expect(text).toContain('恢复整图留档？')
    expect(text).toContain('合并式')
    expect(text).toContain('不覆盖')
    expect(text).toContain('绝不造悬空边')
    expect(text).not.toContain('409')
  })

  it('恢复以 kind=graph 调接口（带库作用域）', async () => {
    const page = await mountPage()
    await page.findAll('tbody tr')[0].trigger('click')
    await flush()
    await button(page, '恢复选中').trigger('click')
    await flush()

    clickDialogButton('恢复')
    await flush()

    expect(vi.mocked(trashApi.restoreTrash).mock.calls[0]).toEqual([
      'graph', 'graph-20261017-144222', undefined,
    ])
  })
})
