import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ApiError, backendBase, formatErrorDetail, qs, req, setBackendBase, setErrorReporter } from '@/api/http'
import { reportClientLog } from '@/api/logs'

describe('formatErrorDetail（FastAPI 错误信封 → 可读文本）', () => {
  it('字符串原样返回', () => {
    expect(formatErrorDetail('Event not found')).toBe('Event not found')
  })

  it('422 校验数组拼成「字段: 消息」，并去掉 body 前缀', () => {
    const detail = [
      { loc: ['body', 'llm_timeout'], msg: 'Input should be greater than 0' },
      { loc: ['body', 'agent_mode'], msg: 'Input should be disabled or pipeline' },
    ]
    expect(formatErrorDetail(detail)).toBe(
      'llm_timeout: Input should be greater than 0; agent_mode: Input should be disabled or pipeline',
    )
  })

  it('对象序列化，不会变成 [object Object]', () => {
    expect(formatErrorDetail({ code: 'E1' })).toBe('{"code":"E1"}')
  })
})

describe('qs', () => {
  it('跳过空值，数组逗号连接', () => {
    expect(qs({ a: 1, b: '', c: undefined, d: null })).toBe('?a=1')
    expect(qs({ repo_ids: ['x', 'y'] })).toBe('?repo_ids=x%2Cy')
    expect(qs({ repo_ids: [] })).toBe('')
    expect(qs({})).toBe('')
  })
})

describe('reportClientLog（前端日志上报，api/logs.ts）', () => {
  const originalFetch = globalThis.fetch

  afterEach(() => {
    globalThis.fetch = originalFetch
    localStorage.clear()
  })

  it('带上 X-API-Key——否则启用 DPIM_API_KEY 的部署里上报全部 401 且被静默吞掉', async () => {
    localStorage.setItem('dpim_api_key', 'secret')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    globalThis.fetch = fetchMock as never

    await reportClientLog('error', 'x'.repeat(9000), '/events')

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(String(url)).toContain('/logs/client')
    expect((init.headers as Record<string, string>)['X-API-Key']).toBe('secret')
    // 上报内容截断到 8000（别让一条超长错误把日志文件撑爆）
    expect((JSON.parse(String(init.body)) as { message: string }).message).toHaveLength(8000)
  })

  it('被拒（401）不抛错、不递归上报，只在 devtools 留痕', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 }) as never

    await expect(reportClientLog('error', 'boom', '/x')).resolves.toBeUndefined()
    expect(warn).toHaveBeenCalled()

    warn.mockRestore()
  })
})

describe('req', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    localStorage.clear()
    setBackendBase('')
    setErrorReporter(null)
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('成功时返回 JSON，并带上认证头（有 key 时）', async () => {
    localStorage.setItem('dpim_api_key', 'secret')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: 1 }),
    })
    globalThis.fetch = fetchMock as never
    await expect(req('/health')).resolves.toEqual({ ok: 1 })
    const init = fetchMock.mock.calls[0][1]
    expect(init.headers['X-API-Key']).toBe('secret')
  })

  it('无 key 时不发送认证头（本地默认无认证）', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) })
    globalThis.fetch = fetchMock as never
    await req('/health')
    expect(fetchMock.mock.calls[0][1].headers['X-API-Key']).toBeUndefined()
  })

  it('204 返回 undefined（无响应体端点）', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, status: 204 }) as never
    await expect(req('/x', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('非 2xx 抛 ApiError，消息取自 detail，并带上状态码', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: async () => ({ detail: 'Node must keep at least one valid source reference' }),
    }) as never
    const err = await req('/nodes/x', { method: 'DELETE' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(409)
    expect((err as ApiError).message).toContain('at least one valid source reference')
  })

  it('网络不可达时给出「后端不可达 + 地址」，而不是裸的 TypeError', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('Failed to fetch')) as never
    const err = await req('/health').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(0)
    expect((err as ApiError).message).toContain('后端不可达')
  })

  it('失败会上报给注入的 reporter（P6：失败留痕进 frontend 日志）', async () => {
    const reporter = vi.fn()
    setErrorReporter(reporter)
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'ISE',
      json: async () => ({ detail: '落盘失败' }),
    }) as never
    await req('/events', { method: 'POST', body: '{}' }).catch(() => undefined)
    expect(reporter).toHaveBeenCalledTimes(1)
    expect(reporter.mock.calls[0][0]).toBe('error')
    expect(reporter.mock.calls[0][1]).toContain('落盘失败')
  })

  it('backendBase 可读写（配置页改后端地址）', () => {
    setBackendBase('http://127.0.0.1:9000')
    expect(backendBase()).toBe('http://127.0.0.1:9000')
    setBackendBase('')
    expect(backendBase()).toBe('')
  })
})
