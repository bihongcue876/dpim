<template>
  <span class="badge" :class="`badge--${kind}`">
    <span class="badge-dot" aria-hidden="true" />
    {{ text }}
  </span>
</template>

<script setup lang="ts">
/**
 * 原文 / 衍生 标识（统一层）。
 *
 * P3 原文不可擅改：界面必须**看得见**地区分
 *   - `origin`（线层原文：按时间追加，仅人类可显式修订）
 *   - `derived`（图层衍生：AI 从原文提炼，可由 AI 维护）
 * 两者用不同色系与文案，禁止混为一谈。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ kind: 'origin' | 'derived'; text?: string }>(),
  { text: '' },
)

const text = computed(
  () => props.text || (props.kind === 'origin' ? '原文 · 仅人类可修订' : '衍生知识 · 可由 AI 维护'),
)
</script>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--dpim-space-1);
  padding: 2px var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
  border: var(--dpim-hairline) solid transparent;
}
.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.badge--origin {
  color: var(--dpim-origin-fg);
  background: var(--dpim-origin-bg);
  border-color: var(--dpim-origin-border);
}
.badge--derived {
  color: var(--dpim-derived-fg);
  background: var(--dpim-derived-bg);
  border-color: var(--dpim-derived-border);
}
</style>
