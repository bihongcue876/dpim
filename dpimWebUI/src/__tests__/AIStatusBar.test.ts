import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AIStatusBar from '@/components/AIStatusBar.vue'

vi.mock('@/api/client', () => ({
  getSettings: vi.fn().mockResolvedValue({
    llm_base_url: 'http://localhost:11434/v1', llm_model_name: 'llama3:8b',
  }),
}))

function health(ai: boolean) {
  return {
    status: ai ? 'ok' : 'degraded',
    ai_available: ai,
    layers: {
      event_line: { total_events: 12 },
      knowledge_graph: { total_nodes: 340 },
    },
    last_event_at: '',
    version: '0.1.0',
  }
}

describe('AIStatusBar', () => {
  it('shows ready when ai available', async () => {
    const wrapper = mount(AIStatusBar, { props: { health: health(true) } })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('AI 就绪')
    expect(wrapper.text()).toContain('340')
    expect(wrapper.text()).toContain('12')
  })

  it('shows not connected when ai unavailable', async () => {
    const wrapper = mount(AIStatusBar, { props: { health: health(false) } })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('未连接上')
    expect(wrapper.text()).toContain('仅支持建立全文索引')
  })
})
