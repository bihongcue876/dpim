/**
 * 周期轮询（composable）：仅在页面挂载期间生效，卸载即停（避免后台空转）。
 */
import { onUnmounted, ref } from 'vue'
import type { Ref } from 'vue'

export function usePolling(task: () => void | Promise<void>, intervalMs = 15000): {
  active: Ref<boolean>
  start: () => void
  stop: () => void
  tick: () => Promise<void>
} {
  const active = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  async function tick(): Promise<void> {
    await task()
  }

  function start(): void {
    stop()
    active.value = true
    void tick()
    timer = setInterval(() => void tick(), intervalMs)
  }

  function stop(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    active.value = false
  }

  onUnmounted(stop)

  return { active, start, stop, tick }
}
