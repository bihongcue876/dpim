/** 本地日志（api 域：logs）——前后端日志分文件，按天轮转 */
import { apiKey, qs, req } from './http'
import type { ClientLogRequest, LogsResponse } from './types'

export interface ListLogsParams {
  /** backend | frontend */
  kind?: string
  /** YYYY-MM-DD；缺省 = 最新一天 */
  date?: string
  level?: string
  keyword?: string
  tail?: number
}

export function listLogs(p: ListLogsParams): Promise<LogsResponse> {
  return req<LogsResponse>(
    `/logs${qs({
      kind: p.kind,
      date: p.date,
      level: p.level,
      keyword: p.keyword,
      tail: p.tail,
    })}`,
  )
}

/**
 * 前端日志送入后端 `frontend-*.log`。
 * 刻意不抛错、不递归上报：日志通道自身失败绝不能再制造失败。
 *
 * **必须带 `X-API-Key`**：后端 `auth_guard` 对**所有**端点生效（没给 `/logs/client` 豁免），
 * 旧实现只发 Content-Type → 设了 `DPIM_API_KEY` 的部署里上报**全部 401**，又被下面的 catch
 * 静默吞掉 → 日志页的 frontend 通道永远空的，且用户看不到任何原因。
 * 失败时只写 `console.warn`（devtools 可见），不制造用户可见噪声。
 */
export async function reportClientLog(
  level: ClientLogRequest['level'],
  message: string,
  source = '',
): Promise<void> {
  try {
    const key = apiKey()
    const res = await fetch(`${localStorage.getItem('dpim_backend_url') || ''}/logs/client`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(key ? { 'X-API-Key': key } : {}),
      },
      body: JSON.stringify({ level, message: message.slice(0, 8000), source }),
      keepalive: true,
    })
    if (!res.ok) console.warn(`[dpim] 前端日志上报被拒：HTTP ${res.status} ${source}`)
  } catch (e) {
    console.warn(`[dpim] 前端日志上报失败：${(e as Error).message} ${source}`)
  }
}
