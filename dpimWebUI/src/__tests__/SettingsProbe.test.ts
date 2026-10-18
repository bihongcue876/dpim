/**
 * 模型探测接口（v1.34）：`POST /settings/models`
 *
 * 用户诉求是「模型可以选择」——前端一键拉取该提供商的真实模型列表。
 * 这里守住三条：请求形状正确、错误原文透传（可见失败）、不抛异常。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { probeProviderModels } from '@/api/settings'
import { setBackendBase, setErrorReporter } from '@/api/http'

describe('probeProviderModels', () => {
  const originalFetch = globalThis.fetch
  let calls: Array<{ url: string; init: RequestInit }> = []

  beforeEach(() => {
    calls = []
    localStorage.clear()
    setBackendBase('')
    setErrorReporter(null)
    globalThis.fetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init })
      return new Response(
        JSON.stringify({
          models: ['deepseek-ai/DeepSeek-V4-Flash', 'Qwen/Qwen3.5-4B'],
          error: '',
          elapsed_ms: 123,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('POST /settings/models，已登记条目只传名字（密钥留空 = 用已存密钥）', async () => {
    const res = await probeProviderModels({ provider: 'siliconflow' })
    expect(calls[0].url).toContain('/settings/models')
    expect(calls[0].init.method).toBe('POST')
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ provider: 'siliconflow' })
    expect(res.models).toEqual(['deepseek-ai/DeepSeek-V4-Flash', 'Qwen/Qwen3.5-4B'])
    expect(res.error).toBe('')
    expect(res.elapsed_ms).toBe(123)
  })

  it('新条目带地址与草稿密钥一起提交', async () => {
    await probeProviderModels({
      base_url: 'http://localhost:5091/v1',
      api_key: 'sk-draft',
    })
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      base_url: 'http://localhost:5091/v1',
      api_key: 'sk-draft',
    })
  })

  it('失败原因原样返回给调用方（不吞、不抛）', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(
        JSON.stringify({ models: [], error: 'APIConnectionError: connection refused', elapsed_ms: 8 }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )) as unknown as typeof fetch
    const res = await probeProviderModels({ base_url: 'http://127.0.0.1:1/v1' })
    expect(res.models).toEqual([])
    expect(res.error).toContain('connection refused')
  })
})
