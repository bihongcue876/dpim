import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusBar from '@/components/StatusBar.vue'

describe('StatusBar', () => {
  const healthOn = {
    status: 'ok', ai_available: true, last_event_at: '2026-07-24T10:00:00Z', version: '0.2.1',
    layers: { event_line: { total_events: 42 }, knowledge_graph: { total_nodes: 7 } },
  }
  const healthOff = {
    status: 'degraded', ai_available: false, last_event_at: '', version: '0.2.1',
    layers: { event_line: {}, knowledge_graph: {} },
  }

  it('renders connection and AI status', () => {
    const wrapper = mount(StatusBar, { props: { connected: true, health: healthOn } })
    expect(wrapper.text()).toContain('42')
    expect(wrapper.text()).toContain('7')
    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain('可用')
  })

  it('shows degraded when AI unavailable', () => {
    const wrapper = mount(StatusBar, { props: { connected: true, health: healthOff } })
    expect(wrapper.text()).toContain('降级')
  })

  it('shows disconnected', () => {
    const wrapper = mount(StatusBar, { props: { connected: false, health: null } })
    expect(wrapper.text()).toContain('断开')
  })
})
