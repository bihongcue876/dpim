<template>
  <aside class="detail">
    <header class="detail-head">
      <div class="detail-head-text">
        <h3 class="detail-title">{{ title }}</h3>
        <p v-if="subtitle" class="detail-subtitle">{{ subtitle }}</p>
      </div>
      <div class="detail-head-actions"><slot name="head-actions" /></div>
    </header>

    <div v-if="$slots.meta" class="detail-meta"><slot name="meta" /></div>

    <!-- 滚动链必须逐层 flex + min-height:0，否则底部操作按钮会被裁掉且不可见（链 O4） -->
    <div class="detail-scroll">
      <slot />
    </div>

    <footer v-if="$slots.actions" class="detail-actions"><slot name="actions" /></footer>
  </aside>
</template>

<script setup lang="ts">
/**
 * 详情容器（统一层）：页头 + 元信息条 + 可滚动正文 + 固定底部操作。
 *
 * 滚动链完整（P2/链 O4）：`.detail` → `.detail-scroll` 每层都写 min-height:0，
 * 保证正文超高时是内部滚动，底部操作始终可见。
 */
withDefaults(defineProps<{ title?: string; subtitle?: string }>(), {
  title: '',
  subtitle: '',
})
</script>

<style scoped>
.detail {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  overflow: hidden;
}
.detail-head {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-3) var(--dpim-space-4);
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
}
.detail-head-text {
  min-width: 0;
}
.detail-title {
  margin: 0;
  font-size: var(--dpim-fs-lg);
  font-weight: 600;
  color: var(--dpim-text);
  line-height: 1.35;
  word-break: break-word;
}
.detail-subtitle {
  margin: var(--dpim-space-1) 0 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.detail-head-actions {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  flex-shrink: 0;
}
.detail-meta {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--dpim-space-2) var(--dpim-space-4);
  padding: var(--dpim-space-2) var(--dpim-space-4);
  background: var(--dpim-surface-2);
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
}
.detail-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--dpim-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-4);
}
.detail-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-3) var(--dpim-space-4);
  border-top: var(--dpim-hairline) solid var(--dpim-border);
  background: var(--dpim-surface);
}
</style>
