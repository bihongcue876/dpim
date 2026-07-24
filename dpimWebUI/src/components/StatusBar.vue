<template>
  <n-layout-footer class="status-bar">
    <span>连接状态: <n-tag :type="connected ? 'success' : 'error'" size="tiny">{{ connected ? '已连接' : '断开' }}</n-tag></span>
    <span>AI 状态: <n-tag :type="aiAvailable ? 'success' : 'warning'" size="tiny">{{ aiAvailable ? '可用' : '降级' }}</n-tag></span>
    <span>事件: {{ totalEvents }}</span>
    <span>节点: {{ totalNodes }}</span>
  </n-layout-footer>
</template>

<script setup lang="ts">
defineProps<{
  connected: boolean
  aiAvailable: boolean
  totalEvents: number
  totalNodes: number
}>()
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  height: 28px;
  padding: 0 12px;
  font-size: 12px;
  border-top: 1px solid var(--n-border-color);
}
</style>
