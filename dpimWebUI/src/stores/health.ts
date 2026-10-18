/**
 * 健康与连接状态（store：health）。
 *
 * P1 可见性：容量 / 队列 / 降级 / 备份份数 / 操作日志条数都必须能在界面上看到，
 * 因此 `/health` 的 v1.30 `storage` 段由本 store 统一持有，顶栏与概览台共用。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '@/api/health'
import type { HealthResponse } from '@/api/types'

const POLL_MS = 30000

export const useHealthStore = defineStore('health', () => {
  const health = ref<HealthResponse | null>(null)
  const connected = ref(true)
  const loading = ref(false)
  const error = ref('')
  const checkedAt = ref<number>(0)

  let timer: ReturnType<typeof setInterval> | null = null

  const aiAvailable = computed(() => health.value?.ai_available ?? false)
  /** v1.34：**没配 AI**（后端 /health 三态之一）——与「配了但连不上」严格区分 */
  const aiUnconfigured = computed(() => health.value?.status === 'unconfigured')
  /** 不可用原因原文（未配置原因 / 连接失败原因），界面直接展示 */
  const aiReason = computed(() => health.value?.ai_unavailable_reason ?? '')
  /** 四态（含后端不可达）：ready / unconfigured / degraded / offline */
  const aiStatus = computed<'ready' | 'unconfigured' | 'degraded' | 'offline'>(() => {
    if (!connected.value) return 'offline'
    if (aiAvailable.value) return 'ready'
    return aiUnconfigured.value ? 'unconfigured' : 'degraded'
  })
  /** 状态文案单一来源（顶栏 / 概览台 / 信息传入共用，避免三处措辞漂移） */
  const aiStatusText = computed(
    () =>
      ({
        ready: 'AI 就绪',
        unconfigured: '未配置 AI · 纯存储可用',
        degraded: 'AI 连不上 · 已降级',
        offline: '后端未连接',
      })[aiStatus.value],
  )
  const degraded = computed(() => aiStatus.value === 'degraded')
  const version = computed(() => health.value?.version ?? '—')
  const storage = computed(() => health.value?.storage ?? null)
  const queueDepth = computed(() => health.value?.queue_depth ?? 0)
  const workerRunning = computed(() => health.value?.worker_running ?? false)
  const lastEventAt = computed(() => health.value?.last_event_at ?? '')
  const eventLine = computed(() => health.value?.layers?.event_line ?? {})
  const graphLayer = computed(() => health.value?.layers?.knowledge_graph ?? {})

  async function refresh(repoId?: string): Promise<void> {
    loading.value = true
    try {
      health.value = await api.getHealth(repoId)
      connected.value = true
      error.value = ''
    } catch (e) {
      connected.value = false
      error.value = (e as Error).message
    } finally {
      loading.value = false
      checkedAt.value = Date.now()
    }
  }

  function start(repoId?: string): void {
    stop()
    void refresh(repoId)
    timer = setInterval(() => void refresh(repoId), POLL_MS)
  }

  function stop(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  return {
    health,
    connected,
    loading,
    error,
    checkedAt,
    aiAvailable,
    aiUnconfigured,
    aiReason,
    aiStatus,
    aiStatusText,
    degraded,
    version,
    storage,
    queueDepth,
    workerRunning,
    lastEventAt,
    eventLine,
    graphLayer,
    refresh,
    start,
    stop,
  }
})
