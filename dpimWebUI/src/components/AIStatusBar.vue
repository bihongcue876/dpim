<template>
  <div class="ai-status" :class="{ offline: !aiOk }">
    <div class="ai-line">
      <span class="ai-dot" :class="{ on: aiOk }"></span>
      <span class="ai-title">{{ aiOk ? 'AI 就绪' : '未连接上' }}</span>
      <template v-if="aiOk && settings">
        <span class="ai-meta">{{ activeModel }} · {{ shortUrl(activeBaseUrl) }}</span>
      </template>
      <span v-else class="ai-meta ai-hint">当前仅支持建立全文索引</span>
    </div>
    <div class="ai-sub">
      <span>上次检查: {{ secondsAgo }} 秒前</span>
      <span v-if="health" class="ai-stats">图层: {{ nodes }} 节点 | 事件: {{ events }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import type { HealthResponse, SettingsResponse } from '@/api/client'
import * as api from '@/api/client'

const props = defineProps<{
  health: HealthResponse | null
}>()

const settings = ref<SettingsResponse | null>(null)
const lastChecked = ref(0)
const secondsAgo = ref(0)

const aiOk = computed(() => Boolean(props.health?.ai_available))
const nodes = computed(() => props.health?.layers?.knowledge_graph?.total_nodes ?? 0)
const events = computed(() => props.health?.layers?.event_line?.total_events ?? 0)

// 显示活动 provider 的模型/地址（注册表优先，primary 回退环境变量）
const activeModel = computed(() => {
  const s = settings.value
  if (!s) return '—'
  const p = s.providers?.[s.active_provider]
  if (s.active_model) return s.active_model
  if (p) {
    const list = p.models ?? (p.model ? [p.model] : [])
    return list[0] ?? '—'
  }
  return s.llm_model_name || '—'
})
const activeBaseUrl = computed(() => {
  const s = settings.value
  if (!s) return ''
  return s.providers?.[s.active_provider]?.base_url || s.llm_base_url || ''
})

function shortUrl(url: string): string {
  try {
    return new URL(url).host || url
  } catch {
    return url
  }
}

let tickTimer: number | null = null
let urlTimer: number | null = null

onMounted(async () => {
  lastChecked.value = Date.now()
  api.getSettings().then(s => (settings.value = s)).catch(() => {})
  tickTimer = window.setInterval(() => {
    secondsAgo.value = Math.max(0, Math.round((Date.now() - lastChecked.value) / 1000))
  }, 1000)
  // 每 30s 刷新一次模型/地址（settings）
  urlTimer = window.setInterval(() => {
    api.getSettings().then(s => (settings.value = s)).catch(() => {})
  }, 30000)
})

onUnmounted(() => {
  if (tickTimer) window.clearInterval(tickTimer)
  if (urlTimer) window.clearInterval(urlTimer)
})

watch(
  () => props.health,
  () => {
    lastChecked.value = Date.now()
  },
)
</script>

<style scoped>
.ai-status {
  display: flex; flex-direction: column; gap: 6px;
  padding: 12px 16px; border-radius: var(--dpim-radius, 12px);
  border: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  background: var(--dpim-surface, #161b22);
  border-left: 3px solid #3fb68b;
}
.ai-status.offline { border-left-color: #f08080; }
.ai-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ai-dot {
  width: 9px; height: 9px; border-radius: 50%;
  background: #f08080; flex-shrink: 0;
  box-shadow: 0 0 0 3px rgba(240,128,128,0.15);
}
.ai-dot.on { background: #3fb68b; box-shadow: 0 0 0 3px rgba(63,182,139,0.15); }
.ai-title { font-weight: 600; font-size: 14px; color: var(--dpim-text, #e6edf3); }
.ai-meta { font-size: 12px; color: var(--dpim-text-3, #7c8694); font-family: 'Cascadia Code', Consolas, monospace; }
.ai-hint { color: #f08080; }
.ai-sub { display: flex; align-items: center; gap: 16px; font-size: 12px; color: var(--dpim-text-3, #7c8694); flex-wrap: wrap; }
.ai-stats { font-family: 'Cascadia Code', Consolas, monospace; }
</style>
