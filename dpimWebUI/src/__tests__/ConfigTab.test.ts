import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfigTab from '@/components/ConfigTab.vue'

vi.mock('@/api/client', () => ({
  getSettings: vi.fn().mockResolvedValue({
    memory_db_path: './data/memory.db', graph_json_path: './data/graph.json',
    llm_base_url: 'http://localhost:11434/v1', llm_api_key: '',
    llm_model_name: 'llama3:8b', llm_timeout: 30, max_graph_hops: 2,
    rrf_k: 60, jaccard_threshold: 0.85, health_check_interval: 60,
    compensate_batch_size: 20, log_level: 'INFO',
  }),
  putSettings: vi.fn().mockResolvedValue(undefined),
}))

describe('ConfigTab', () => {
  const validateOk = vi.fn().mockResolvedValue(true)
  const onCommitted = vi.fn().mockResolvedValue(undefined)

  it('renders all 12 config fields', async () => {
    const wrapper = mount(ConfigTab, {
      props: { health: null, validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('MEMORY_DB_PATH')
    expect(wrapper.text()).toContain('LLM_BASE_URL')
    expect(wrapper.text()).toContain('LLM_API_KEY')
    expect(wrapper.text()).toContain('LOG_LEVEL')
  })

  it('shows submit button at bottom', async () => {
    const wrapper = mount(ConfigTab, {
      props: { health: null, validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('提交配置')
  })
})
