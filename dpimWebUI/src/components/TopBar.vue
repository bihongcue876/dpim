<template>
  <div class="topbar">
    <div class="topbar-left">
      <span class="topbar-title">DPIM 控制台</span>
      <span class="key-badge" :class="keyStatus">{{ badgeText }}</span>
    </div>
    <div class="topbar-right">
      <n-button size="small" :loading="loading" @click="$emit('refresh-key')">
        {{ loading ? '获取中' : '获取最新状态' }}
      </n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  keyStatus: 'unknown' | 'synced' | 'stale'
  loading: boolean
}>()

defineEmits<{ 'refresh-key': [] }>()

const badgeText = computed(() => {
  if (props.keyStatus === 'unknown') return '待校验'
  if (props.keyStatus === 'synced') return '已同步'
  return '数据已变更'
})
const badgeClass = computed(() => props.keyStatus)
</script>

<style scoped>
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  height: 56px; padding: 0 16px;
  border-bottom: 1px solid var(--n-border-color);
  flex-shrink: 0;
}
.topbar-left { display: flex; align-items: center; gap: 10px; }
.topbar-title { font-size: 18px; font-weight: 600; letter-spacing: 1px; }
.key-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
}
.key-badge.unknown { background: #faad1433; color: #faad14; }
.key-badge.synced { background: #52c41a33; color: #52c41a; }
.key-badge.stale { background: #f5222d33; color: #f5222d; }
.topbar-right { display: flex; align-items: center; gap: 8px; }
</style>
