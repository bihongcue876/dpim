import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfigTab from '@/components/ConfigTab.vue'

vi.mock('@/api/client', () => ({
  getSettings: vi.fn().mockResolvedValue({
    memory_db_path: './data/memory.db', graph_json_path: './data/graph.json',
    llm_base_url: 'http://localhost:11434/v1', llm_api_key: '',
    llm_model_name: 'llama3:8b', llm_timeout: 30, llm_max_tokens: null, llm_enable_thinking: null, llm_thinking_budget: null,
    available_providers: ['primary'],
    active_provider: 'primary',
    agent_mode: 'disabled', agent_max_retries: 2, agent_cr_model: '',
    agent_in_model: '', agent_gr_model: '', agent_meta_model: '',
    max_graph_hops: 2, rrf_k: 60, jaccard_threshold: 0.85,
    health_check_interval: 60, health_check_timeout: 60, compensate_batch_size: 20, log_level: 'INFO',
    embedding_model: 'bge-m3', embedding_dim: 1024,
    embedding_base_url: 'https://api.siliconflow.cn/v1', embedding_api_key: 'sk-emb',
  }),
  putSettings: vi.fn().mockResolvedValue(undefined),
}))

describe('ConfigTab', () => {
  const validateOk = vi.fn().mockResolvedValue(true)
  const onCommitted = vi.fn().mockResolvedValue(undefined)

  it('renders config fields including BYOK', async () => {
    const wrapper = mount(ConfigTab, {
      props: { health: null, validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('记忆库路径')
    expect(wrapper.text()).toContain('日志级别')
    expect(wrapper.text()).toContain('后端地址')
    expect(wrapper.text()).toContain('活动提供商')
    expect(wrapper.text()).toContain('Agent 管线模式')
    expect(wrapper.text()).toContain('Meta 模型')
  })

  it('renders embedding config inside model section', async () => {
    const wrapper = mount(ConfigTab, {
      props: { health: null, validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('嵌入模型（空=禁用语义检索）')
    expect(wrapper.text()).toContain('嵌入维度（0=自动检测）')
    expect(wrapper.text()).toContain('嵌入 API 地址（空=跟随活动提供商）')
    expect(wrapper.text()).toContain('嵌入 API Key（空=跟随活动提供商）')
    expect(wrapper.text()).toContain('嵌入服务')
    expect(wrapper.text()).toContain('语义检索状态')
    expect(wrapper.text()).toContain('启用中：bge-m3')
  })

  it('shows submit button at bottom', async () => {
    const wrapper = mount(ConfigTab, {
      props: { health: null, validate: validateOk, onCommitted },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.text()).toContain('提交配置')
  })
})
