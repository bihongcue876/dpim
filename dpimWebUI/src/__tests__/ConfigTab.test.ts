import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfigTab from '@/components/ConfigTab.vue'
import { getSettings, putSettings } from '@/api/client'

vi.mock('@/api/client', () => ({
  getSettings: vi.fn().mockResolvedValue({
    memory_db_path: './data/memory.db', graph_json_path: './data/graph.json',
    llm_base_url: 'http://localhost:11434/v1', llm_api_key: 'sk-****1234',
    llm_model_name: 'llama3:8b', llm_timeout: 30, llm_max_tokens: null, llm_enable_thinking: null, llm_thinking_budget: null,
    available_providers: ['primary', 'siliconflow'],
    providers: {
      siliconflow: {
        base_url: 'https://api.siliconflow.cn/v1',
        api_key: 'sk-****7666',
        models: ['Qwen3.5-9B', 'deepseek-v4'],
      },
    },
    active_provider: 'primary',
    available_models: ['llama3:8b'], active_model: '',
    agent_mode: 'disabled', agent_max_retries: 2, agent_cr_model: '',
    agent_in_model: '', agent_gr_model: '', agent_meta_model: '',
    max_graph_hops: 2, rrf_k: 60, jaccard_threshold: 0.85,
    health_check_interval: 60, health_check_timeout: 60, compensate_batch_size: 20, log_level: 'INFO',
  }),
  putSettings: vi.fn().mockResolvedValue(undefined),
}))

async function flush(ms = 50) {
  await new Promise(r => setTimeout(r, ms))
}

describe('ConfigTab', () => {
  const validateOk = vi.fn().mockResolvedValue(true)
  const onCommitted = vi.fn().mockResolvedValue(undefined)
  const props = { health: null, validate: validateOk, onCommitted }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders config fields including BYOK', async () => {
    const wrapper = mount(ConfigTab, { props })
    await flush()
    expect(wrapper.text()).toContain('记忆库路径')
    expect(wrapper.text()).toContain('日志级别')
    expect(wrapper.text()).toContain('后端地址')
    expect(wrapper.text()).toContain('活动提供商')
    expect(wrapper.text()).toContain('Agent 管线模式')
    expect(wrapper.text()).toContain('Meta 模型')
  })

  it('does not render embedding fields after removal', async () => {
    const wrapper = mount(ConfigTab, { props })
    await flush()
    expect(wrapper.text()).not.toContain('嵌入式模型')
    expect(wrapper.text()).not.toContain('语义检索')
  })

  it('shows submit button at bottom', async () => {
    const wrapper = mount(ConfigTab, { props })
    await flush()
    expect(wrapper.text()).toContain('提交配置')
  })

  // ── 安全：providers 表单化 + 密钥掩码 ──

  it('renders provider cards instead of raw JSON textarea', async () => {
    const wrapper = mount(ConfigTab, { props })
    await flush()
    // JSON textarea 已移除
    expect(wrapper.text()).not.toContain('提供商注册表(JSON)')
    expect(wrapper.find('textarea').exists()).toBe(false)
    // 卡片化：显示名称与掩码密钥
    expect(wrapper.text()).toContain('siliconflow')
    expect(wrapper.text()).toContain('sk-****7666')
    expect(wrapper.text()).toContain('2 个模型')
    expect(wrapper.text()).toContain('新增提供商')
  })

  it('does not render main API key field (primary key managed via .env/dpim.json)', async () => {
    const wrapper = mount(ConfigTab, { props })
    await flush()
    // 主配置 API Key 行已移除：primary 密钥经 .env（DPIM_LLM_API_KEY）或 dpim.json 管理
    expect(wrapper.text()).not.toContain('主配置 API Key')
  })

  it('renders agent role models as selects with follow option', async () => {
    const wrapper = mount(ConfigTab, { props })
    await flush()
    // 管线四个角色模型为下拉框（不再是手敲文本框）
    expect(wrapper.text()).toContain('Cr 模型')
    expect(wrapper.text()).toContain('Meta 模型')
    expect(wrapper.text()).not.toContain('空=活动提供商')
  })

  it('submit does not send anything when unchanged', async () => {
    const wrapper = mount(ConfigTab, { props })
    await flush()
    // 未修改任何字段直接提交 → changed 为空，不调用后端
    const btn = wrapper.findAll('button').find(b => b.text().includes('提交配置'))
    await btn!.trigger('click')
    await flush(100)
    expect(putSettings).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('没有需要保存的修改')
  })

  it('add-provider modal flow updates draft and submits providers', async () => {
    document.body.innerHTML = ''
    const wrapper = mount(ConfigTab, { props, attachTo: document.body })
    await flush()
    // 打开新增弹窗（NModal teleport 到 body）
    const addBtn = wrapper.findAll('button').find(b => b.text().includes('新增提供商'))
    await addBtn!.trigger('click')
    await flush(20)
    const nameInput = document.querySelector('input[placeholder="如 siliconflow"]') as HTMLInputElement
    expect(nameInput).toBeTruthy()
    const setInput = (el: HTMLInputElement | HTMLTextAreaElement, value: string) => {
      el.value = value
      el.dispatchEvent(new Event('input'))
    }
    setInput(nameInput, 'deepseek')
    const urlInput = document.querySelector('input[placeholder="https://api.siliconflow.cn/v1"]') as HTMLInputElement
    setInput(urlInput, 'http://localhost:5091/v1')
    const keyInput = document.querySelector('input[placeholder^="sk-"]') as HTMLInputElement
    setInput(keyInput, 'sk-real-new-key')
    const modelsArea = document.querySelector('textarea[placeholder^="逗号或换行分隔"]') as HTMLTextAreaElement
    setInput(modelsArea, 'deepseek-v4, deepseek-r1')
    // 点保存
    const saveBtn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent!.trim() === '保存')
    await saveBtn!.dispatchEvent(new Event('click'))
    await flush(20)
    // 草稿进卡片
    expect(wrapper.text()).toContain('deepseek')
    // 提交 → providers 变更随 payload 发送
    const submitBtn = wrapper.findAll('button').find(b => b.text().includes('提交配置'))
    await submitBtn!.trigger('click')
    await flush(100)
    expect(putSettings).toHaveBeenCalledTimes(1)
    const payload = (putSettings as ReturnType<typeof vi.fn>).mock.calls[0][0]
    expect(payload.providers).toBeDefined()
    expect(payload.providers.deepseek).toMatchObject({
      base_url: 'http://localhost:5091/v1',
      api_key: 'sk-real-new-key',
      models: ['deepseek-v4', 'deepseek-r1'],
    })
    wrapper.unmount()
    document.body.innerHTML = ''
  })

  it('keeps original masked key when editing provider without touching key', async () => {
    document.body.innerHTML = ''
    const wrapper = mount(ConfigTab, { props, attachTo: document.body })
    await flush()
    // 编辑已有 provider：卡片的「编辑」按钮
    const editBtn = wrapper.findAll('button').find(b => b.text() === '编辑')
    await editBtn!.trigger('click')
    await flush(20)
    const urlInput = document.querySelector('input[placeholder="https://api.siliconflow.cn/v1"]') as HTMLInputElement
    expect(urlInput).toBeTruthy()
    expect(urlInput.value).toBe('https://api.siliconflow.cn/v1')
    // API Key 输入框保持空（不回填），提示当前掩码
    const keyInput = document.querySelector('input[placeholder^="当前 sk-"]') as HTMLInputElement
    expect(keyInput).toBeTruthy()
    expect(keyInput.value).toBe('')
    // 修改 base_url 触发变更（key 依然不动）
    urlInput.value = 'https://api2.siliconflow.cn/v1'
    urlInput.dispatchEvent(new Event('input'))
    const saveBtn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent!.trim() === '保存')
    await saveBtn!.dispatchEvent(new Event('click'))
    await flush(20)
    const submitBtn = wrapper.findAll('button').find(b => b.text().includes('提交配置'))
    await submitBtn!.trigger('click')
    await flush(100)
    const payload = (putSettings as ReturnType<typeof vi.fn>).mock.calls[0][0]
    // 未输入新 key → 回传原掩码值（后端幂等保留现值）
    expect(payload.providers.siliconflow.api_key).toBe('sk-****7666')
    expect(payload.providers.siliconflow.base_url).toBe('https://api2.siliconflow.cn/v1')
    wrapper.unmount()
    document.body.innerHTML = ''
  })

  it('renames provider and submits renamed key', async () => {
    document.body.innerHTML = ''
    const wrapper = mount(ConfigTab, { props, attachTo: document.body })
    await flush()
    // 编辑唯一 provider「siliconflow」→ 改名「sf2」
    const editBtn = wrapper.findAll('button').find(b => b.text() === '编辑')
    await editBtn!.trigger('click')
    await flush(20)
    const nameInput = document.querySelector('input[placeholder="如 siliconflow"]') as HTMLInputElement
    expect(nameInput).toBeTruthy()
    expect(nameInput.value).toBe('siliconflow') // 编辑弹窗名称可编辑且预填现名
    nameInput.value = 'sf2'
    nameInput.dispatchEvent(new Event('input'))
    const saveBtn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent!.trim() === '保存')
    await saveBtn!.dispatchEvent(new Event('click'))
    await flush(20)
    // 卡片以新名展示
    expect(wrapper.text()).toContain('sf2')
    // 提交 → providers 以新名发送，旧名消失
    const submitBtn = wrapper.findAll('button').find(b => b.text().includes('提交配置'))
    await submitBtn!.trigger('click')
    await flush(100)
    const payload = (putSettings as ReturnType<typeof vi.fn>).mock.calls[0][0]
    expect(payload.providers).toHaveProperty('sf2')
    expect(payload.providers).not.toHaveProperty('siliconflow')
    expect(payload.providers.sf2.api_key).toBe('sk-****7666') // 改名保留密钥掩码（幂等回传）
    wrapper.unmount()
    document.body.innerHTML = ''
  })

  it('blocks renaming provider to an existing name (duplicate check)', async () => {
    document.body.innerHTML = ''
    const wrapper = mount(ConfigTab, { props, attachTo: document.body })
    await flush()
    // 先新增 provider「deepseek」
    const addBtn = wrapper.findAll('button').find(b => b.text().includes('新增提供商'))
    await addBtn!.trigger('click')
    await flush(20)
    let nameInput = document.querySelector('input[placeholder="如 siliconflow"]') as HTMLInputElement
    nameInput.value = 'deepseek'
    nameInput.dispatchEvent(new Event('input'))
    const urlInput = document.querySelector('input[placeholder="https://api.siliconflow.cn/v1"]') as HTMLInputElement
    urlInput.value = 'http://localhost:5091/v1'
    urlInput.dispatchEvent(new Event('input'))
    let saveBtn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent!.trim() === '保存')
    await saveBtn!.dispatchEvent(new Event('click'))
    await flush(20)
    // 编辑第一张卡（排序后 deepseek 在前）→ 改名「siliconflow」→ 查重报错、保存禁用
    const editBtn = wrapper.findAll('button').find(b => b.text() === '编辑')
    await editBtn!.trigger('click')
    await flush(20)
    nameInput = document.querySelector('input[placeholder="如 siliconflow"]') as HTMLInputElement
    nameInput.value = 'siliconflow'
    nameInput.dispatchEvent(new Event('input'))
    await flush(20)
    expect(document.body.textContent).toContain('名称「siliconflow」已存在')
    saveBtn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent!.trim() === '保存')!
    expect((saveBtn as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
    document.body.innerHTML = ''
  })
})
