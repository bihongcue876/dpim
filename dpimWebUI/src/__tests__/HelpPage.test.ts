/**
 * 帮助（HelpPage）页面级单测 —— 链 AE（§十 遗留待办 #5：剩余页面级单测）。
 *
 * 本页是**用户供稿的正文**（链 X 明确要求保留），几乎没有逻辑，但正因为"没人看代码"
 * 才需要一层守卫：正文段落被误删 / 结构被改坏时，用例要报出来。
 * 另外守住两个**用户可见的承诺**必须写在帮助里：
 * ① 未配置 AI 也能用（降级为基础全文检索，恢复后自动补偿）；
 * ② 中文检索靠 FTS5 召回不足时降级 LIKE。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

import HelpPage from '@/pages/HelpPage.vue'

const Blank = defineComponent({ template: '<div />' })

async function flush(): Promise<void> {
  await flushPromises()
  await flushPromises()
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/help', name: 'help', component: Blank }],
  })
  await router.push('/help')
  await router.isReady()
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(HelpPage) }),
  })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  await flush()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
})

describe('HelpPage（帮助）', () => {
  it('用户供稿正文的结构完整（五个章节都在）', async () => {
    const page = await mountPage()
    const text = page.text()

    expect(text).toContain('DPIM 双区智能记忆系统 · 使用说明')
    expect(text).toContain('DPIM 是什么')
    expect(text).toContain('基本功能')
    expect(text).toContain('书目与分组')
    expect(text).toContain('DPIM Web UI 使用方法')
    expect(text).toContain('常见问题')
  })

  it('把两条用户可见承诺写清楚：无 AI 也能用、中文检索会降级', async () => {
    const page = await mountPage()
    const text = page.text()

    expect(text).toContain('没有配置 AI 模型还能用吗？')
    expect(text).toContain('未配置或断连时系统降级为基础全文检索存储')
    expect(text).toContain('中文检索如何工作？')
    expect(text).toContain('召回不足时自动降级为 LIKE 检索')
  })

  it('术语与状态机口径与协议一致（raw → indexed → linked 终态）', async () => {
    const page = await mountPage()
    const text = page.text()

    expect(text).toContain('raw（待处理）')
    expect(text).toContain('indexed（已索引）')
    expect(text).toContain('linked（已关联图谱，终态）')
    expect(text).toContain('linked 为终态不可回退')
  })
})
