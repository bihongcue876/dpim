<template>
  <div class="statusbar">
    <span class="sb-item">
      连接: <n-tag size="tiny" :type="connected ? 'success' : 'error'" :bordered="false">{{ connected ? '已连接' : '断开' }}</n-tag>
    </span>
    <span class="sb-item">
      AI: <n-tag size="tiny" :type="health?.ai_available ? 'success' : 'warning'" :bordered="false">{{ health?.ai_available ? '可用' : '降级' }}</n-tag>
    </span>
    <span class="sb-item">事件: {{ health?.layers?.event_line?.total_events ?? '—' }}</span>
    <span class="sb-item">节点: {{ health?.layers?.knowledge_graph?.total_nodes ?? '—' }}</span>
  </div>
</template>

<script setup lang="ts">
import type { HealthResponse } from '@/api/client'

defineProps<{
  health: HealthResponse | null
  connected: boolean
}>()
</script>

<style scoped>
.statusbar {
  display: flex; align-items: center; gap: 16px;
  height: 28px; padding: 0 16px; font-size: 12px;
  border-top: 1px solid var(--n-border-color);
  flex-shrink: 0;
}
.sb-item { display: flex; align-items: center; gap: 4px; }
</style>
