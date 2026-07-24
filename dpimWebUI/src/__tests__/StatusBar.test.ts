import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusBar from '@/components/StatusBar.vue'

describe('StatusBar', () => {
  it('renders connection and AI status', () => {
    const wrapper = mount(StatusBar, {
      props: { connected: true, aiAvailable: true, totalEvents: 42, totalNodes: 7 },
    })
    expect(wrapper.text()).toContain('42')
    expect(wrapper.text()).toContain('7')
    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain('可用')
  })

  it('shows degraded when AI unavailable', () => {
    const wrapper = mount(StatusBar, {
      props: { connected: true, aiAvailable: false, totalEvents: 0, totalNodes: 0 },
    })
    expect(wrapper.text()).toContain('降级')
  })

  it('shows disconnected when not connected', () => {
    const wrapper = mount(StatusBar, {
      props: { connected: false, aiAvailable: false, totalEvents: 0, totalNodes: 0 },
    })
    expect(wrapper.text()).toContain('断开')
  })
})
