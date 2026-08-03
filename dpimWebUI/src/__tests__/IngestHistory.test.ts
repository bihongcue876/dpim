import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import IngestHistory from '@/components/IngestHistory.vue'

describe('IngestHistory', () => {
  const base = {
    event_id: '1722000000000-abc',
    submitted_at: '2026-08-01T12:00:00Z',
  }

  it('shows empty state', () => {
    const wrapper = mount(IngestHistory, { props: { items: [] } })
    expect(wrapper.text()).toContain('暂无提交记录')
  })

  it('renders linked with node count', () => {
    const wrapper = mount(IngestHistory, {
      props: { items: [{ ...base, status: 'linked', node_count: 2 }] },
    })
    expect(wrapper.text()).toContain('已关联 (2节点)')
  })

  it('renders processing/failed/timeout labels', () => {
    const wrapper = mount(IngestHistory, {
      props: {
        items: [
          { ...base, event_id: 'a', status: 'processing' },
          { ...base, event_id: 'b', status: 'failed' },
          { ...base, event_id: 'c', status: 'timeout' },
        ],
      },
    })
    expect(wrapper.text()).toContain('处理中...')
    expect(wrapper.text()).toContain('处理失败')
    expect(wrapper.text()).toContain('处理超时')
  })

  it('emits select on id click', async () => {
    const wrapper = mount(IngestHistory, {
      props: { items: [{ ...base, status: 'linked', node_count: 1 }] },
    })
    const idEl = wrapper.find('.ih-id')
    await idEl.trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual(['1722000000000-abc'])
  })
})
