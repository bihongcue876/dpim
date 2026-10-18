<template>
  <div class="state-block" :class="{ 'state-block--fixed': fixedHeight }">
    <template v-if="loading">
      <span class="state-spinner" aria-hidden="true" />
      <p class="state-text">{{ loadingText }}</p>
    </template>
    <template v-else-if="error">
      <span class="state-icon state-icon--error">!</span>
      <p class="state-text state-text--error">{{ error }}</p>
      <slot name="retry" />
    </template>
    <template v-else>
      <span class="state-icon">{{ icon }}</span>
      <p class="state-text">{{ emptyText }}</p>
      <p v-if="hint" class="state-hint">{{ hint }}</p>
      <slot name="extra" />
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 三态块（统一层）：loading / error / empty 共用同一位置与高度，避免切换时跳动。
 *
 * P6 失败可见：错误态必须显示后端原文，不允许退化成一句「加载失败」。
 */
withDefaults(
  defineProps<{
    loading?: boolean
    error?: string
    emptyText?: string
    /** 空态补充说明（告诉用户下一步做什么） */
    hint?: string
    loadingText?: string
    icon?: string
    /** 固定高度（列表/详情并列时防止布局跳动），默认撑满容器 */
    fixedHeight?: boolean
  }>(),
  {
    loading: false,
    error: '',
    emptyText: '暂无内容',
    hint: '',
    loadingText: '加载中…',
    icon: '·',
    fixedHeight: false,
  },
)
</script>

<style scoped>
.state-block {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-5);
  text-align: center;
  color: var(--dpim-text-3);
  font-size: var(--dpim-fs-md);
  line-height: 1.5;
}
.state-block--fixed {
  min-height: 180px;
  flex: none;
}
.state-text {
  margin: 0;
}
.state-text--error {
  color: var(--dpim-danger);
  max-width: 60ch;
  word-break: break-word;
}
.state-hint {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  max-width: 56ch;
}
.state-icon {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: var(--dpim-fs-md);
  background: var(--dpim-surface-2);
  color: var(--dpim-text-3);
}
.state-icon--error {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.state-spinner {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid var(--dpim-border-strong);
  border-top-color: var(--dpim-primary);
  animation: dpim-spin 0.8s linear infinite;
}
@keyframes dpim-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
