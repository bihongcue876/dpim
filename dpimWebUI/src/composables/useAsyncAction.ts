/**
 * 异步动作（composable）：统一的「执行中 / 成功 / 失败原因」三态。
 *
 * P6 失败可见：失败必须留下 `error` 供页面常驻展示，不能只在 toast 里闪一下。
 */
import { ref } from 'vue'
import type { Ref } from 'vue'

export interface AsyncAction<A extends unknown[], R> {
  running: Ref<boolean>
  error: Ref<string>
  lastResult: Ref<R | null>
  /** 执行并捕获错误；返回 null 表示失败（错误已在 error 中） */
  run: (...args: A) => Promise<R | null>
  reset: () => void
}

export function useAsyncAction<A extends unknown[], R>(
  action: (...args: A) => Promise<R>,
): AsyncAction<A, R> {
  const running = ref(false)
  const error = ref('')
  const lastResult = ref<R | null>(null) as Ref<R | null>

  async function run(...args: A): Promise<R | null> {
    running.value = true
    error.value = ''
    try {
      const result = await action(...args)
      lastResult.value = result
      return result
    } catch (e) {
      error.value = (e as Error).message
      return null
    } finally {
      running.value = false
    }
  }

  function reset(): void {
    error.value = ''
    lastResult.value = null
  }

  return { running, error, lastResult, run, reset }
}
