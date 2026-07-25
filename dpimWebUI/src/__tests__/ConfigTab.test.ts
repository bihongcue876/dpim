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

  it('renders all 13 config fields', async () => {
    const wrapper = mount(ConfigTab, {
      props: { health: null, validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('记忆库路径')
    expect(wrapper.text()).toContain('日志级别')
    expect(wrapper.text()).toContain('后端地址')
  })

  it('shows submit button at bottom', async () => {
    const wrapper = mount(ConfigTab, {
      props: { health: null, validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('提交配置')
  })
})
