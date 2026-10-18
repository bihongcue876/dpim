import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { createRouter, createMemoryHistory, RouterView, type Router } from 'vue-router'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useUnsavedGuard } from '@/composables/useUnsavedGuard'

const Blank = defineComponent({ render: () => h('div') })
/** 经 router-view 渲染页面：`onBeforeRouteLeave` **只对由路由渲染的组件**生效（直接 mount 组件时守卫不会挂到路由上） */
const Host = defineComponent({ render: () => h(RouterView) })

let mounted: VueWrapper | null = null

/** 造一个「带守卫的页面」+ 一个「别的页面」，返回路由与脏标记 */
async function setup(dirty: boolean, message?: string) {
  const isDirty = ref(dirty)
  const Page = defineComponent({
    setup() {
      useUnsavedGuard(() => isDirty.value, message)
      return () => h('div', 'page')
    },
  })
  const router: Router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/draft', name: 'draft', component: Page },
      { path: '/other', name: 'other', component: Blank },
    ],
  })
  await router.push('/draft')
  await router.isReady()
  // 上一个用例的组件必须先卸掉：否则它的 `beforeunload` 监听器还挂着，会跨用例误拦
  mounted?.unmount()
  mounted = mount(Host, { global: { plugins: [router] } })
  await router.isReady()
  return { router, isDirty }
}

describe('useUnsavedGuard（未保存草稿的离开守卫）', () => {
  let confirmSpy: MockInstance

  beforeEach(() => {
    confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    mounted?.unmount()
    mounted = null
    confirmSpy.mockRestore()
  })

  it('没有改动时直接放行，连确认框都不弹', async () => {
    const { router } = await setup(false)
    await router.push('/other')
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(router.currentRoute.value.path).toBe('/other')
  })

  it('有改动且用户确认 → 放行', async () => {
    const { router } = await setup(true)
    await router.push('/other')
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.path).toBe('/other')
  })

  it('有改动且用户取消 → **留在原页**（草稿不丢）', async () => {
    confirmSpy.mockReturnValue(false)
    const { router } = await setup(true)
    await router.push('/other')
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.path).toBe('/draft')
  })

  it('确认文案可自定义（页面能说清「丢的是什么」）', async () => {
    const { router } = await setup(true, '提供商配置还没提交，离开将丢失。确定离开吗？')
    await router.push('/other')
    expect(confirmSpy.mock.calls[0][0]).toContain('提供商配置还没提交')
  })

  it('刷新/关闭页面时按脏标记拦截 beforeunload', async () => {
    const { isDirty } = await setup(true)

    const blocked = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(blocked)
    expect(blocked.defaultPrevented).toBe(true)

    // 改动已提交（脏标记归位）→ 不再拦截
    isDirty.value = false
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)

    // 组件卸载后监听器要摘掉，否则会跨页面误拦
    mounted?.unmount()
    mounted = null
    const after = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(after)
    expect(after.defaultPrevented).toBe(false)
  })
})
