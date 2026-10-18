/**
 * 运行配置页（SettingsPage）页面级单测 —— v1.36「可配置面补齐 + 来源可见」。
 *
 * 缺口由来：此前只测了来源标签组件（SettingsSource.test.ts）与模型探测 API（SettingsProbe.test.ts），
 * 页面本身没有页面级单测（AGENTS 遗留待办 #3）。这一组用例守住四类回归：
 * ① v1.36 新增的 14 个可配置字段真的按板块渲染出来，且后端值确实装进了控件；
 * ② 被环境变量顶掉的项**置灰 + 点名是哪个变量**（否则又是「改了没效果」的静默失败）；
 * ③ 未锁定的项可改，旁边标出取值来源（已存 dpim.json / 默认值）；
 * ④ 提交只下发**改动过**的字段；后端 `ignored_by_env` 点名的项必须在页面顶部看得见。
 *
 * 取数一律 mock 在 API 模块层（`@/api/settings` / `@/api/health` / `@/api/repos`），
 * 与 EventsPage / ReposPage / layout 的既有做法一致——不碰 http.ts，也不起 fetch。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h } from 'vue'
import { NMessageProvider } from 'naive-ui'

vi.mock('@/api/settings', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  probeProviderModels: vi.fn(),
}))
vi.mock('@/api/health', () => ({
  getHealth: vi.fn(),
  getStateHash: vi.fn(),
  getAgentLogs: vi.fn(),
  compensate: vi.fn(),
  maintain: vi.fn(),
}))
vi.mock('@/api/repos', () => ({
  listRepos: vi.fn(),
  activateRepo: vi.fn(),
  generateRepo: vi.fn(),
  selectableRepos: (repos: any[]) => repos.filter((r: any) => r.managed && r.loaded),
}))

import * as settingsApi from '@/api/settings'
import * as healthApi from '@/api/health'
import SettingsPage from '@/pages/SettingsPage.vue'

/**
 * `GET /settings` 的 v1.36 响应：字段名取真实契约（`share/protocol.ts` 的 SettingsResponse），
 * 值取内置默认，便于断言「值确实渲染出来了」。
 * 提供商注册表留空——本组用例只关心配置字段，空注册表让 payload 断言更干净。
 */
function settingsFixture(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    // 存储路径与日志级别
    memory_db_path: 'D:/dpim/data/memory.db',
    graph_json_path: 'D:/dpim/data/graph.json',
    log_level: 'INFO',
    // 提供商注册表（v1.34：AI 身份只在这里）
    providers: {},
    available_providers: [],
    active_provider: '',
    available_models: [],
    active_model: '',
    llm_configured: false,
    llm_unavailable_reason: '未配置任何 AI 提供商（无 AI 模式）',
    // Agent 管线
    agent_mode: 'disabled',
    agent_max_retries: 3,
    agent_cr_model: '',
    agent_in_model: '',
    agent_gr_model: '',
    agent_meta_model: '',
    llm_structured_mode: 'md_json',
    // 检索与护栏
    max_graph_hops: 2,
    rrf_k: 60,
    jaccard_threshold: 0.85,
    max_raw_content: 200000,
    // 健康检查与补偿
    health_check_interval: 60,
    health_check_timeout: 30,
    compensate_batch_size: 20,
    compensate_check_interval: 30,
    // 图维护自动化
    agent_maintain_auto: true,
    agent_maintain_min_nodes: 10,
    agent_maintain_max_nodes: 200,
    agent_maintain_cooldown: 60,
    agent_cmdmsg_max_rounds: 3,
    agent_cr_skip_chars: 200,
    // 本地日志与 WAL
    log_retention_days: 14,
    log_jsonl: false,
    agent_logs_full: true,
    wal_checkpoint_interval: 300,
    wal_checkpoint_bytes: 8388608,
    // 保留策略（v1.39）
    graph_ops_retention: 5000,
    trash_retention_days: 30,
    // v1.36 只读可见性
    config_file: 'D:/dpim/config/dpim.json',
    log_dir: 'D:/dpim/logs',
    config_sources: {},
    ...over,
  }
}

const Blank = defineComponent({ template: '<div />' })

/** 让 onMounted 里的两串 await（load / loadLogs）以及提交链路全部落地 */
async function flush(): Promise<void> {
  await flushPromises()
  await flushPromises()
}

/**
 * 轮询等待条件成立。
 * 为什么不用固定次数的 `flush()`：全量跑（21 个文件并行 + 机器忙）时两次 flush 可能不够，
 * 于是出现「单独跑通过、全量跑失败」的假失败。条件成立即返回，最多等 `tries` 轮。
 */
async function waitFor(cond: () => boolean, tries = 30): Promise<void> {
  for (let i = 0; i < tries; i += 1) {
    if (cond()) return
    await flush()
  }
}

async function mountPage(over: Record<string, unknown> = {}) {
  // **上一个用例的页面必须先卸掉**：它 teleport 出去的弹窗仍留在 `document` 里，而本文件的
  // `dialogText()` / `clickDialogButton()` 是**文档级**查询 → 会读到上一个用例的弹窗；
  // 未卸载组件的异步续体也会在下一个用例里触发请求，造成「单独跑通过、全量跑失败」。
  mountedPage?.unmount()
  vi.mocked(settingsApi.getSettings).mockResolvedValue(settingsFixture(over) as never)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', name: 'settings', component: Blank }],
  })
  await router.push('/settings')
  await router.isReady()
  // useMessage() 需要 provider 祖先（与 ReposPage / EventsPage 的既有做法一致）
  const Host = defineComponent({
    render: () => h(NMessageProvider, null, { default: () => h(SettingsPage) }),
  })
  const wrapper = mount(Host, { global: { plugins: [router] } })
  mountedPage = wrapper
  await flush()
  return wrapper
}

type Page = Awaited<ReturnType<typeof mountPage>>

/** 当前挂载的页面（下一次 `mountPage` 时卸载，见那里的注释） */
let mountedPage: { unmount: () => void } | null = null

/** 按字段标签定位一行：不依赖控件顺序与 DOM 层级，加字段不会让用例串位 */
function rowOf(page: Page, label: string): DOMWrapper<Element> {
  const rows = page.findAll('.field-row')
  const hit = rows.find((r) => {
    const l = r.find('.field-label label')
    return l.exists() && l.text() === label
  })
  if (!hit) {
    const known = rows.map((r) => r.find('.field-label label').text()).join(' / ')
    throw new Error(`未找到字段行「${label}」；页面上现有字段行：${known}`)
  }
  return hit
}

/** 行内数值控件当前显示的值（n-input-number 的 input.value） */
function numberValueOf(page: Page, label: string): string {
  const el = rowOf(page, label).find('input').element as HTMLInputElement
  return el.value
}

/** 行内控件是否置灰：DOM 属性与特性两路都认，避免 Vue 打属性/打特性的差异 */
function isDisabledRow(page: Page, label: string): boolean {
  const el = rowOf(page, label).find('input').element as HTMLInputElement
  return el.disabled || el.hasAttribute('disabled')
}

/** 改一个数值字段：走 n-input-number 的 `v-model:value` 事件，与真实交互同一条链路 */
async function setNumber(page: Page, label: string, value: number): Promise<void> {
  await rowOf(page, label).findComponent({ name: 'InputNumber' }).setValue(value, 'value')
  await flush()
}

function submitButton(page: Page): DOMWrapper<Element> {
  const btn = page.findAll('button').find((b) => b.text() === '提交配置')
  if (!btn) {
    throw new Error(`未找到「提交配置」按钮；现有按钮：${page.findAll('button').map((b) => b.text()).join(' / ')}`)
  }
  return btn
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = '' // 清掉上一用例挂载/teleport 出去的节点
  vi.mocked(healthApi.getStateHash).mockResolvedValue({ hash: 'k', changed_at: '' } as never)
  vi.mocked(healthApi.getAgentLogs).mockResolvedValue({ logs: [] } as never)
  vi.mocked(healthApi.compensate).mockResolvedValue({ message: '已触发补偿' } as never)
  vi.mocked(healthApi.maintain).mockResolvedValue({ message: '已入队图维护' } as never)
  vi.mocked(settingsApi.probeProviderModels).mockResolvedValue({
    models: [],
    error: '',
    elapsed_ms: 0,
  } as never)
  vi.mocked(settingsApi.putSettings).mockResolvedValue({
    status: 'ok',
    message: '配置已保存',
  } as never)
})

describe('SettingsPage（运行配置）', () => {
  it('v1.36 新增字段按板块渲染，且后端值确实装进了控件', async () => {
    const page = await mountPage()
    const text = page.text()

    // 板块分组在（v1.36 新增的三个板块 + 既有的健康检查）
    expect(text).toContain('检索与护栏')
    expect(text).toContain('健康检查与补偿')
    expect(text).toContain('图维护自动化')
    expect(text).toContain('本地日志与 WAL')

    // v1.36 新增字段全部有可见的标签
    expect(text).toContain('单次输入字符上限')
    expect(text).toContain('补偿结果检查间隔（秒）')
    expect(text).toContain('自动维护开关')
    expect(text).toContain('自动维护最小节点数')
    expect(text).toContain('节点规模高水位')
    expect(text).toContain('高水位冷却（秒）')
    expect(text).toContain('指令消息轮次封顶')
    expect(text).toContain('Cr 短路阈值（字符）')
    expect(text).toContain('日志保留天数')
    expect(text).toContain('额外输出 JSONL')
    expect(text).toContain('AI 调用日志取全文')
    expect(text).toContain('WAL 检查点周期（秒）')
    expect(text).toContain('WAL 触发体积（字节）')
    // v1.39 保留策略（独立板块：graph_ops 表与回收站目录的有界化）
    expect(text).toContain('保留策略')
    expect(text).toContain('图层操作日志保留条数')
    expect(text).toContain('回收站留档保留天数')
    // 结构化输出模式（v1.36 新增，在 Agent 管线板块）
    expect(text).toContain('结构化输出模式')

    // 值确实从 GET /settings 装进了控件（不是空壳）
    expect(numberValueOf(page, '单次输入字符上限')).toBe('200000')
    expect(numberValueOf(page, '节点规模高水位')).toBe('200')
    expect(numberValueOf(page, 'WAL 检查点周期（秒）')).toBe('300')
    expect(numberValueOf(page, 'WAL 触发体积（字节）')).toBe('8388608')
    expect(numberValueOf(page, '图层操作日志保留条数')).toBe('5000')
    expect(numberValueOf(page, '回收站留档保留天数')).toBe('30')
  })

  it('env 锁定的字段置灰，并点名是哪个环境变量（不再静默无效）', async () => {
    const page = await mountPage({
      config_sources: { rrf_k: 'env:DPIM_RRF_K', max_raw_content: 'env:DPIM_MAX_RAW_CONTENT' },
    })

    expect(isDisabledRow(page, 'RRF 参数 K')).toBe(true)
    expect(isDisabledRow(page, '单次输入字符上限')).toBe(true)

    const text = page.text()
    expect(text).toContain('环境变量')
    expect(text).toContain('DPIM_RRF_K')
    expect(text).toContain('由环境变量 DPIM_RRF_K 决定（界面不可改）')
  })

  it('未锁定的字段可编辑，旁边标出来源（已存 dpim.json / 默认值）', async () => {
    const page = await mountPage({
      config_sources: { max_raw_content: 'file', wal_checkpoint_interval: 'default' },
    })

    expect(isDisabledRow(page, '单次输入字符上限')).toBe(false)
    expect(rowOf(page, '单次输入字符上限').find('.chip--file').text()).toBe('已存 dpim.json')
    expect(rowOf(page, 'WAL 检查点周期（秒）').find('.chip--muted').text()).toBe('默认值')
  })

  it('只读卡片显示后端读写的配置文件与日志目录', async () => {
    const page = await mountPage()
    const text = page.text()

    expect(text).toContain('配置来源')
    expect(text).toContain('配置文件')
    expect(text).toContain('D:/dpim/config/dpim.json')
    expect(text).toContain('日志目录')
    expect(text).toContain('D:/dpim/logs')
  })

  it('提交只下发改动过的字段（没动的字段不进 payload）', async () => {
    const page = await mountPage()
    await setNumber(page, '单次输入字符上限', 300000)
    // 先确认改动确实进了控件（否则下面的 payload 断言可能「假通过」）
    expect(numberValueOf(page, '单次输入字符上限')).toBe('300000')

    await submitButton(page).trigger('click')
    await flush()

    expect(settingsApi.putSettings).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(settingsApi.putSettings).mock.calls[0][0]
    expect(Object.keys(payload)).toEqual(['max_raw_content'])
    expect(payload).toEqual({ max_raw_content: 300000 })
  })

  it('ignored_by_env 在页面顶部点名「由环境变量锁定、本次未生效」', async () => {
    // 后端点名了哪些项就显示哪些项，前端不自己推断：
    // 来源可能在两次读取之间变化（例如改了 .env 后重启），或界面版本较旧仍提交了锁定项。
    vi.mocked(settingsApi.putSettings).mockResolvedValue({
      status: 'ok',
      message: '配置已保存',
      ignored_by_env: ['rrf_k(DPIM_RRF_K)'],
    } as never)

    const page = await mountPage({ config_sources: { rrf_k: 'env:DPIM_RRF_K' } })
    await setNumber(page, '单次输入字符上限', 300000)
    await submitButton(page).trigger('click')
    await flush()

    // 提交结果横幅常驻可见（不是一闪而过的 message）
    expect(page.find('.banner--ok').exists()).toBe(true)
    const locked = page.find('.banner-locked')
    expect(locked.exists()).toBe(true)
    expect(locked.text()).toContain('以下项由环境变量锁定，本次未生效：')
    expect(locked.text()).toContain('rrf_k(DPIM_RRF_K)')

    const text = page.text()
    expect(text).toContain('配置已保存并写入 dpim.json')
    expect(text).toContain('部分项被环境变量锁定')
  })
})

// ── v1.43：提供商「接口格式」（openai / responses / anthropic / custom）──
//
// 弹窗内容由 `n-modal` teleport 到 `document.body`，所以弹窗里的文本与按钮要查
// `document`（`page.text()` 里没有它们）——与 TrashPage 用例同一套做法。

/** body 级按钮（弹窗内、页面内都能命中；同名按钮请先确认唯一） */
function bodyButton(text: string): HTMLElement {
  const btn = Array.from(document.querySelectorAll('button')).find(
    (b) => (b.textContent ?? '').trim() === text,
  )
  if (!btn) {
    const known = Array.from(document.querySelectorAll('button'))
      .map((b) => (b.textContent ?? '').trim())
      .join(' / ')
    throw new Error(`未找到按钮「${text}」；现有：${known}`)
  }
  return btn as HTMLElement
}

/** 页面内的按钮（`mount` 未 attachTo body，页面 DOM 不在 document 里） */
function pageButton(page: Page, text: string): DOMWrapper<Element> {
  const btn = page.findAll('button').find((b) => b.text() === text)
  if (!btn) {
    throw new Error(
      `未找到按钮「${text}」；现有：${page.findAll('button').map((b) => b.text()).join(' / ')}`,
    )
  }
  return btn
}

function dialogText(): string {
  return document.querySelector('.modal-box')?.textContent ?? ''
}

function clickDialogButton(text: string): void {
  const btns = Array.from(document.querySelectorAll('.modal-actions button'))
  const hit = btns.find((b) => (b.textContent ?? '').trim() === text) as HTMLElement | undefined
  if (!hit) {
    throw new Error(
      `弹窗里未找到按钮「${text}」；现有：${btns.map((b) => b.textContent?.trim()).join(' / ')}`,
    )
  }
  hit.click()
}

/** 弹窗里的「接口格式」下拉：按选项内容定位，不依赖控件顺序 */
function formatSelect(page: Page) {
  const hit = page.findAllComponents({ name: 'Select' }).find((c) => {
    const opts = (c.props('options') ?? []) as Array<{ value?: string }>
    return opts.some((o) => o.value === 'anthropic')
  })
  if (!hit) throw new Error('未找到「接口格式」下拉')
  return hit
}

/** 按 placeholder 定位弹窗里的输入框（名称 / Base URL / 请求路径 / 额外请求头） */
async function setInputByPlaceholder(page: Page, needle: string, value: string): Promise<void> {
  const hit = page
    .findAllComponents({ name: 'Input' })
    .find((c) => String(c.props('placeholder') ?? '').includes(needle))
  if (!hit) throw new Error(`未找到占位符含「${needle}」的输入框`)
  await hit.setValue(value, 'value')
  await flush()
}

describe('SettingsPage 提供商接口格式（v1.43）', () => {
  async function openDialog(): Promise<Page> {
    const page = await mountPage()
    await pageButton(page, '新增提供商').trigger('click')
    await flush()
    return page
  }

  it('弹窗有「接口格式」一项，四套协议都在选项里，默认 OpenAI 兼容', async () => {
    const page = await openDialog()

    expect(dialogText()).toContain('接口格式')
    const values = (formatSelect(page).props('options') as Array<{ value: string }>).map(
      (o) => o.value,
    )
    expect(values).toEqual(['openai', 'responses', 'anthropic', 'custom'])
    expect(dialogText()).toContain('chat/completions') // 默认那套的说明
  })

  it('切到 Anthropic：说明点明 x-api-key 与 max_tokens 必填，地址占位换成官方端点', async () => {
    const page = await openDialog()
    await formatSelect(page).setValue('anthropic', 'value')
    await flush()

    expect(dialogText()).toContain('x-api-key')
    expect(dialogText()).toContain('max_tokens 必填')
    const baseUrl = page
      .findAllComponents({ name: 'Input' })
      .find((c) => String(c.props('placeholder') ?? '').includes('anthropic.com'))
    expect(baseUrl).toBeTruthy()
  })

  it('切到自定义：才露出「请求路径」与「额外请求头」', async () => {
    const page = await openDialog()
    expect(dialogText()).not.toContain('请求路径')

    await formatSelect(page).setValue('custom', 'value')
    await flush()

    expect(dialogText()).toContain('请求路径')
    expect(dialogText()).toContain('api_path')
    expect(dialogText()).toContain('额外请求头')
  })

  it('保存自定义条目：卡片显示格式与路径，提交时下发 format/api_path/extra_headers', async () => {
    const page = await openDialog()
    await formatSelect(page).setValue('custom', 'value')
    await flush()
    await setInputByPlaceholder(page, 'siliconflow', 'gw')
    await setInputByPlaceholder(page, 'your-gateway', 'https://gw.local/v1')
    await setInputByPlaceholder(page, '/chat/completions', '/chat/custom')
    await setInputByPlaceholder(page, 'X-API-Key', '{"X-API-Key": "k1"}')
    clickDialogButton('保存')
    await flush()

    // 卡片读的是 providersDraft：格式标签与自定义路径都必须看得见
    expect(page.text()).toContain('自定义')
    expect(page.text()).toContain('/chat/custom')

    await submitButton(page).trigger('click')
    await flush()

    const payload = vi.mocked(settingsApi.putSettings).mock.calls[0][0] as {
      providers?: Record<string, Record<string, unknown>>
    }
    expect(payload.providers?.gw).toMatchObject({
      base_url: 'https://gw.local/v1',
      format: 'custom',
      api_path: '/chat/custom',
      extra_headers: { 'X-API-Key': 'k1' },
    })
  })

  it('OpenAI 兼容（缺省）不往条目里写 format —— 老条目形状保持干净', async () => {
    const page = await openDialog()
    await setInputByPlaceholder(page, 'siliconflow', 'sf')
    await setInputByPlaceholder(page, 'siliconflow.cn', 'https://api.siliconflow.cn/v1')
    clickDialogButton('保存')
    await flush()

    await submitButton(page).trigger('click')
    await flush()
    const payload = vi.mocked(settingsApi.putSettings).mock.calls[0][0] as {
      providers?: Record<string, Record<string, unknown>>
    }
    expect(payload.providers?.sf).toBeTruthy()
    expect('format' in (payload.providers?.sf ?? {})).toBe(false)
    expect('api_path' in (payload.providers?.sf ?? {})).toBe(false)
  })

  it('额外请求头不是合法 JSON：当场拦下、不发 PUT、弹窗不关', async () => {
    const page = await openDialog()
    await formatSelect(page).setValue('custom', 'value')
    await flush()
    await setInputByPlaceholder(page, 'siliconflow', 'gw')
    await setInputByPlaceholder(page, 'your-gateway', 'https://gw.local/v1')
    await setInputByPlaceholder(page, 'X-API-Key', '{不是 JSON')
    clickDialogButton('保存')
    await flush()

    expect(dialogText()).toContain('额外请求头（extra_headers）不是合法 JSON')
    expect(document.querySelector('.modal-box')).toBeTruthy() // 弹窗还在
    expect(settingsApi.putSettings).not.toHaveBeenCalled()
  })

  it('弹窗内「拉取模型列表」把当前选的格式一起发出去', async () => {
    const page = await openDialog()
    await formatSelect(page).setValue('anthropic', 'value')
    await flush()
    await setInputByPlaceholder(page, 'anthropic.com', 'https://api.anthropic.com/v1')
    bodyButton('拉取模型列表').click()
    await flush()

    expect(vi.mocked(settingsApi.probeProviderModels).mock.calls[0][0]).toMatchObject({
      base_url: 'https://api.anthropic.com/v1',
      format: 'anthropic',
    })
  })
})

describe('SettingsPage 输出上限与思考预算（v1.44）', () => {
  async function openDialog(): Promise<Page> {
    const page = await mountPage()
    await pageButton(page, '新增提供商').trigger('click')
    await flush()
    return page
  }

  it('「输出上限」提示按格式说清「留空会发出去什么」，不含糊地说「默认」', async () => {
    const page = await openDialog()
    // 默认那套（OpenAI 兼容）：留空 = 不传，服务端决定
    expect(dialogText()).toContain('留空 = 不传，由服务端决定')

    await formatSelect(page).setValue('anthropic', 'value')
    await flush()

    // Anthropic：必填 + 兜底 4096 + 「上限不是目标长度」+ 思考余量规则，三句都要在
    expect(dialogText()).toContain('Anthropic 必填：留空按 4096 发送')
    expect(dialogText()).toContain('上限而不是目标长度')
    expect(dialogText()).toContain('思考预算 + 1024')
  })

  it('卡片显示实际生效的输出上限（Anthropic 未填 → 默认（4096））', async () => {
    const page = await mountPage({
      providers: {
        claude: {
          base_url: 'https://api.anthropic.com/v1',
          format: 'anthropic',
          models: ['claude-sonnet-4-5'],
        },
      },
    })

    expect(page.text()).toContain('输出上限 默认（4096）')
  })

  it('思考预算比上限大：卡片点名会被抬到多少（后端确实会抬，界面必须说出来）', async () => {
    const page = await mountPage({
      providers: {
        claude: {
          base_url: 'https://api.anthropic.com/v1',
          format: 'anthropic',
          models: ['claude-sonnet-4-5'],
          max_tokens: 2048,
          thinking_budget: 4096,
        },
      },
    })

    expect(page.text()).toContain('输出上限 2048（思考预算更大，实际按 5120）')
  })
})

describe('SettingsPage 密钥不外显 + 卡片拉取用草稿（v1.45）', () => {
  /**
   * 与用户实测那条 OpenCode 密钥**同形状**的**合成**密钥（前缀 `oc_sk_` 与长度一致，值全假）。
   * 用途只有一个：断言「明文不得出现在界面上」。
   * ⚠️ 这里**绝不允许**放真实密钥——测试文件会进 git 历史，写进去就洗不掉了。
   */
  const SECRET = 'oc_sk_000000000000_FAKE_KEY_FOR_TESTS_ONLY_00-0000'
  const MASK = `${SECRET.slice(0, 3)}****${SECRET.slice(-4)}`

  async function openDialog(): Promise<Page> {
    const page = await mountPage()
    await pageButton(page, '新增提供商').trigger('click')
    await flush()
    return page
  }

  /** 填一个 Anthropic 格式的条目并保存（= 进草稿，不提交） */
  async function fillAndSave(page: Page): Promise<void> {
    await formatSelect(page).setValue('anthropic', 'value')
    await flush()
    await setInputByPlaceholder(page, 'siliconflow', 'opencode')
    await setInputByPlaceholder(page, 'anthropic.com', 'https://opencode.ai/zen/go/v1/')
    await setInputByPlaceholder(page, 'sk-…', SECRET)
    clickDialogButton('保存')
    await flush()
  }

  it('保存弹窗后：卡片与再次打开的占位符都只有掩码，明文一次都不出现', async () => {
    const page = await openDialog()
    await fillAndSave(page)
    await waitFor(() => page.text().includes(MASK))

    // 卡片：显示掩码、绝不显示明文（旧实现把明文写进草稿 → 卡片直接渲染明文）
    expect(page.text()).toContain(MASK)
    expect(page.text()).not.toContain(SECRET)

    // 弹窗占位符「当前 …，留空保持不变」同样必须是掩码
    await pageButton(page, '编辑').trigger('click')
    await waitFor(() => dialogText().includes(MASK))
    expect(dialogText()).toContain(MASK)
    expect(dialogText()).not.toContain(SECRET)
  })

  it('提交配置时下发真值：草稿存掩码，但后端必须收到明文（否则密钥静默丢失）', async () => {
    const page = await openDialog()
    await fillAndSave(page)

    await submitButton(page).trigger('click')
    await waitFor(() => vi.mocked(settingsApi.putSettings).mock.calls.length > 0)

    const payload = vi.mocked(settingsApi.putSettings).mock.calls[0][0] as {
      providers?: Record<string, Record<string, unknown>>
    }
    expect(payload.providers?.opencode?.api_key).toBe(SECRET)
    expect(payload.providers?.opencode?.format).toBe('anthropic')
  })

  it('卡片「拉取模型」带草稿的地址/密钥/格式——未提交的条目也能拉（旧实现只发名字 → 「未填模型地址」）', async () => {
    vi.mocked(settingsApi.probeProviderModels).mockResolvedValue({
      models: ['claude-sonnet-4', 'claude-haiku-4'],
      error: '',
      elapsed_ms: 12,
    } as never)

    const page = await openDialog()
    await fillAndSave(page)
    vi.mocked(settingsApi.probeProviderModels).mockClear()

    await pageButton(page, '拉取模型').trigger('click')
    await waitFor(() => vi.mocked(settingsApi.probeProviderModels).mock.calls.length > 0)

    expect(vi.mocked(settingsApi.probeProviderModels).mock.calls[0][0]).toMatchObject({
      provider: 'opencode',
      base_url: 'https://opencode.ai/zen/go/v1/',
      api_key: SECRET, // 草稿里是掩码，拉取要用真值（后端对掩码 = 保持现值）
      format: 'anthropic',
    })
    // 探测结果要落到卡片上（`waitFor` 在「调用发生」时就返回了，此处再等渲染）
    await waitFor(() => page.text().includes('已拉取 2 个模型'))
    expect(page.text()).toContain('已拉取 2 个模型')
  })

  it('条目没有地址时，卡片拉取给出可下手的提示（而不是让后端含糊地回「未填模型地址」）', async () => {
    vi.mocked(settingsApi.probeProviderModels).mockClear()
    // 已存条目可以是空地址（坏配置 / 旧 dpim.json）——弹窗保存那条路有「请填写 Base URL」拦着
    const page = await mountPage({
      providers: { broken: { base_url: '', api_key: '', models: [] } },
    })

    await pageButton(page, '拉取模型').trigger('click')
    await flush()

    expect(settingsApi.probeProviderModels).not.toHaveBeenCalled()
    expect(page.text()).toContain('该条目还没填地址（base_url）')
  })
})
