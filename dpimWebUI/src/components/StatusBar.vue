<template>
  <div class="statusbar">
    <div class="sb-group">
      <span class="sb-item">
        <span class="sb-label">连接</span>
        <n-tag size="tiny" :type="connected ? 'success' : 'error'" :bordered="false">{{ connected ? '已连接' : '断开' }}</n-tag>
      </span>
      <span class="sb-divider"></span>
      <span class="sb-item">
        <span class="sb-label">AI</span>
        <n-tag size="tiny" :type="health?.ai_available ? 'success' : 'warning'" :bordered="false">{{ health?.ai_available ? '可用' : '降级' }}</n-tag>
      </span>
      <span class="sb-divider"></span>
      <span class="sb-item">
        <span class="sb-label">事件</span>
        <span class="sb-num">{{ health?.layers?.event_line?.total_events ?? '—' }}</span>
      </span>
      <span class="sb-divider"></span>
      <span class="sb-item">
        <span class="sb-label">节点</span>
        <span class="sb-num">{{ health?.layers?.knowledge_graph?.total_nodes ?? '—' }}</span>
      </span>
      <template v-if="lastEventText">
        <span class="sb-divider"></span>
        <span class="sb-item">
          <span class="sb-label">最近事件</span>
          <span class="sb-meta">{{ lastEventText }}</span>
        </span>
      </template>
    </div>
    <div class="sb-right">
      <span v-if="health?.version" class="sb-version">v{{ health.version }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { HealthResponse } from '@/api/client'

const props = defineProps<{
  health: HealthResponse | null
  connected: boolean
}>()

const lastEventText = computed(() => {
  const t = props.health?.last_event_at
  if (!t) return ''
  const d = new Date(t)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', { hour12: false })
})
</script>

<style scoped>
.statusbar {
  display: flex; align-items: center; justify-content: space-between;
  height: 28px; padding: 0 20px; font-size: 12px;
  background: var(--dpim-surface, #161b22);
  border-top: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  flex-shrink: 0;
}
.sb-group { display: flex; align-items: center; gap: 14px; min-width: 0; }
.sb-item { display: flex; align-items: center; gap: 6px; }
.sb-label { color: var(--dpim-text-3, #7c8694); }
.sb-num { color: var(--dpim-text, #e6edf3); font-family: 'Cascadia Code', Consolas, monospace; font-weight: 600; }
.sb-meta { color: var(--dpim-text-2, #aab4c0); font-family: 'Cascadia Code', Consolas, monospace; font-size: 11px; }
.sb-divider { width: 1px; height: 12px; background: var(--dpim-border, rgba(255,255,255,0.09)); }
.sb-right { display: flex; align-items: center; }
.sb-version { color: var(--dpim-text-3, #7c8694); font-family: 'Cascadia Code', Consolas, monospace; font-size: 11px; letter-spacing: 0.5px; }
</style>
