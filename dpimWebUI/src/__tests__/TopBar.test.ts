import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TopBar from '@/components/TopBar.vue'

describe('TopBar', () => {
  it('renders title', () => {
    const wrapper = mount(TopBar, { props: { hashStatus: 'locked' } })
    expect(wrapper.text()).toContain('DPIM Web UI')
  })

  it('shows 已锁定 tag when locked', () => {
    const wrapper = mount(TopBar, { props: { hashStatus: 'locked' } })
    expect(wrapper.text()).toContain('已锁定')
    expect(wrapper.text()).toContain('点"更新"后再操作')
  })

  it('shows 已解锁 tag when unlocked', () => {
    const wrapper = mount(TopBar, { props: { hashStatus: 'unlocked' } })
    expect(wrapper.text()).toContain('已解锁')
    expect(wrapper.text()).not.toContain('点"更新"后再操作')
  })

  it('shows 校验中 tag during loading', () => {
    const wrapper = mount(TopBar, { props: { hashStatus: 'loading' } })
    expect(wrapper.text()).toContain('校验中')
  })

  it('emits refresh-hash on update button click', async () => {
    const wrapper = mount(TopBar, { props: { hashStatus: 'locked' } })
    // Naive UI n-button renders as a native button with .n-button class
    const btn = wrapper.find('button')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('refresh-hash')).toBeTruthy()
    expect(wrapper.emitted('refresh-hash')!.length).toBe(1)
  })
})
