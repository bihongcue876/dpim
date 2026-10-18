/**
 * HTTP 基座（重设计：api/ 按域拆分，本文件是唯一出口）。
 *
 * 职责：后端地址 / 认证头 / 统一错误信封解析 / 查询串构造 / 失败上报。
 * 不含任何业务端点。
 */

const BACKEND_URL_KEY = 'dpim_backend_url'
const API_KEY_KEY = 'dpim_api_key'

/** 后端地址（空 = 走同源 / vite 代理） */
export function backendBase(): string {
  try {
    return localStorage.getItem(BACKEND_URL_KEY) || ''
  } catch {
    return ''
  }
}

export function setBackendBase(url: string): void {
  try {
    localStorage.setItem(BACKEND_URL_KEY, url)
  } catch {
    /* 隐私模式等：忽略，本次会话仍按空地址走代理 */
  }
}

export function apiKey(): string {
  try {
    return localStorage.getItem(API_KEY_KEY) || ''
  } catch {
    return ''
  }
}

export function setApiKey(key: string): void {
  try {
    localStorage.setItem(API_KEY_KEY, key)
  } catch {
    /* 同上 */
  }
}

/**
 * 清除已保存的访问密钥：**真删** localStorage 里的键（`removeItem`，不是写空串）。
 *
 * 为什么必须真删：写空串会在浏览器 profile 里留下痕迹之外，更关键是「空串 = 未设置」与
 * 「有值」的判定要一致；用户撤销密钥的诉求是「这东西别再留在我机器上」。
 * 隐私模式等异常照旧容错（与 `apiKey`/`setApiKey` 同一口径）。
 */
export function clearApiKey(): void {
  try {
    localStorage.removeItem(API_KEY_KEY)
  } catch {
    /* 同上 */
  }
}

/** 请求失败的结构化错误：状态码 + 后端原文（不吞） */
export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type ErrorReporter = (level: 'warning' | 'error', message: string, source: string) => void

let errorReporter: ErrorReporter | null = null

/**
 * 注入失败上报（main.ts 接到 api/logs 的 reportClientLog）。
 * 用注入而非直接 import，避免 http ←→ logs 的循环依赖。
 */
export function setErrorReporter(fn: ErrorReporter | null): void {
  errorReporter = fn
}

function reportFailure(message: string, source: string): void {
  if (!errorReporter) return
  try {
    errorReporter('error', message, source)
  } catch {
    /* 上报自身失败绝不能再抛 */
  }
}

/**
 * 上报用路径：**剥掉查询串**。
 * 查询串里可能是用户输入（`events`/`nodes` 的 `query`、`logs` 的 `keyword`、`maintenance` 的 `note`），
 * 而后端 `POST /logs/client` 会把它写进 `logs/frontend-*.log`（留磁盘、日志页可翻看）——检索词不外泄。
 */
function reportPath(path: string): string {
  return path.split('?')[0]
}

/** FastAPI 错误信封 → 可读文本（detail 可能是字符串 / 422 数组 / 对象） */
export function formatErrorDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const item = d as { loc?: unknown[]; msg?: unknown }
        // loc 形如 ['body','llm_timeout']：去掉 'body' 前缀，让报错直接指向字段名
        const loc = Array.isArray(item?.loc)
          ? item.loc.filter((x) => typeof x === 'string' && x !== 'body').join('.')
          : ''
        const msg = typeof item?.msg === 'string' ? item.msg : String(d)
        return loc ? `${loc}: ${msg}` : msg
      })
      .join('; ')
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail)
    } catch {
      return String(detail)
    }
  }
  return String(detail)
}

/** 构造查询串：跳过 undefined / null / 空串 / 空数组 */
export function qs(params: Record<string, unknown>): string {
  const q = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      if (value.length === 0) continue
      q.set(key, value.join(','))
      continue
    }
    q.set(key, String(value))
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

/** 统一请求：JSON 入出 + 认证头 + 错误信封解析 */
export async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const url = backendBase() + path
  let res: Response
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(apiKey() ? { 'X-API-Key': apiKey() } : {}),
        ...init?.headers,
      },
    })
  } catch (e) {
    const msg = `后端不可达：${backendBase() || location.origin}${path}`
    // 上报内容同样剥掉查询串（抛给界面的 msg 仍带完整地址：它只在内存/界面出现，不落盘）
    reportFailure(
      `后端不可达：${backendBase() || location.origin}${reportPath(path)}（${(e as Error).message}）`,
      reportPath(path),
    )
    throw new ApiError(msg, 0)
  }

  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      const body = await res.json()
      detail = body?.detail ?? body?.message ?? body?.error?.message ?? res.statusText
    } catch {
      /* 非 JSON 响应（如代理 502 的 HTML）→ 用 statusText */
    }
    const msg = formatErrorDetail(detail)
    // 上报只送**剥掉查询串**的路径（理由见 reportPath）：message 与 source 两处都不带用户检索词
    reportFailure(`${res.status} ${reportPath(path)} → ${msg}`, reportPath(path))
    throw new ApiError(msg, res.status)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
