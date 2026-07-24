<template>
  <n-layout-header class="top-bar">
    <div class="top-bar-left">
      <n-tag :type="hashStatus === 'unlocked' ? 'success' : hashStatus === 'loading' ? 'warning' : 'default'">
        {{ hashStatus === 'unlocked' ? '已解锁' : hashStatus === 'loading' ? '校验中' : '已锁定' }}
      </n-tag>
      <span v-if="hashStatus === 'locked'" class="hash-hint">数据可能已变更，请点"更新"后再操作</span>
    </div>
    <div class="top-bar-title">DPIM Web UI</div>
    <div class="top-bar-right">
      <n-button size="small" @click="$emit('refresh-hash')" :loading="hashStatus === 'loading'">更新</n-button>
    </div>
  </n-layout-header>
</template>

<script setup lang="ts">
defineProps<{ hashStatus: string }>()
defineEmits<{ 'refresh-hash': [] }>()
</script>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 40px;
  padding: 0 12px;
  border-bottom: 1px solid var(--n-border-color);
}
.top-bar-left { display: flex; align-items: center; gap: 8px; }
.top-bar-title { font-weight: 600; font-size: 15px; }
.top-bar-right { display: flex; align-items: center; gap: 8px; }
.hash-hint { font-size: 12px; color: var(--n-text-color-3); }
</style>
