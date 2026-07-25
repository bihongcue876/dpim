import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TopBar from '@/components/TopBar.vue'

describe('TopBar', () => {
  it('renders title', () => {
    const wrapper = mount(TopBar, { props: { keyStatus: 'unknown', loading: false } })
    expect(wrapper.text()).toContain('DPIM 控制台')
  })

  it('shows unknown badge by default', () => {
    const wrapper = mount(TopBar, { props: { keyStatus: 'unknown', loading: false } })
    expect(wrapper.text()).toContain('待校验')
  })

  it('shows synced badge', () => {
    const wrapper = mount(TopBar, { props: { keyStatus: 'synced', loading: false } })
    expect(wrapper.text()).toContain('已同步')
  })

  it('shows stale badge', () => {
    const wrapper = mount(TopBar, { props: { keyStatus: 'stale', loading: false } })
    expect(wrapper.text()).toContain('数据已变更')
  })

  it('emits refresh-key on button click', async () => {
    const wrapper = mount(TopBar, { props: { keyStatus: 'unknown', loading: false } })
    const btn = wrapper.find('button')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('refresh-key')).toBeTruthy()
  })
})
