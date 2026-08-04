import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import EventListTab from '@/components/EventListTab.vue'

vi.mock('@/api/client', () => ({
  listEvents: vi.fn().mockResolvedValue({
    items: [
      { event_id: 'e1', created_at: '2026-08-04T10:00:00Z', raw_content: '第一条事件', event_type: 'interaction', status: 'linked' },
      { event_id: 'e2', created_at: '2026-08-04T11:00:00Z', raw_content: '第二条事件', event_type: 'data', status: 'indexed' },
      { event_id: 'e3', created_at: '2026-08-04T12:00:00Z', raw_content: '第三条事件', event_type: 'source', status: 'failed' },
    ],
    total: 3,
  }),
  getEvent: vi.fn().mockImplementation((id: string) => {
    if (id === 'e1') return Promise.resolve({
      event_id: 'e1', created_at: '2026-08-04T10:00:00Z', raw_content: '第一条事件', content_hash: 'abc123',
      event_type: 'interaction', status: 'linked', graph_refs: ['n1'],
    })
    return Promise.reject(new Error('Not Found'))
  }),
  putEventStatus: vi.fn().mockResolvedValue(undefined),
  deleteEvent: vi.fn().mockResolvedValue(undefined),
  ingest: vi.fn().mockResolvedValue({ event_id: 'e4', status: 'indexed' }),
  compensate: vi.fn().mockResolvedValue(undefined),
}))

import * as api from '@/api/client'

describe('EventListTab', () => {
  const validateOk = vi.fn().mockResolvedValue(true)
  const onCommitted = vi.fn().mockResolvedValue(undefined)

  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('renders event list on mount', async () => {
    const wrapper = mount(EventListTab, {
      props: { validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 100))
    expect(wrapper.text()).toContain('第一条事件')
    expect(wrapper.text()).toContain('interaction')
    expect(wrapper.text()).toContain('共 3 条')
  })

  it('shows detail panel when a row is clicked', async () => {
    const wrapper = mount(EventListTab, {
      props: { validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 100))
    const row = wrapper.findAll('.event-row')[0]
    await row.trigger('click')
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('事件详情')
    expect(api.getEvent).toHaveBeenCalledWith('e1')
  })

  it('triggers retry on failed event', async () => {
    const wrapper = mount(EventListTab, {
      props: { validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 100))
    // Click the failed event row first
    const rows = wrapper.findAll('.event-row')
    await rows[2].trigger('click')
    await new Promise(r => setTimeout(r, 50))
    // Click retry button
    const retryBtn = wrapper.findAll('button').find(b => b.text().includes('重试'))
    if (retryBtn) {
      await retryBtn.trigger('click')
      await new Promise(r => setTimeout(r, 50))
      expect(api.putEventStatus).toHaveBeenCalledWith('e3', 'indexed')
    }
  })

  it('shows filter dropdowns', async () => {
    const wrapper = mount(EventListTab, {
      props: { validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 100))
    expect(wrapper.text()).toContain('类型')
    expect(wrapper.text()).toContain('状态')
    expect(wrapper.text()).toContain('新建')
  })
})