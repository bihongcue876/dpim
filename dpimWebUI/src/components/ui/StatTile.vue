<template>
  <div class="tile" :class="{ 'tile--wide': wide }">
    <p class="tile-label">{{ label }}</p>
    <p class="tile-value" :class="[`tile-value--${tone}`]">
      {{ value }}<span v-if="unit" class="tile-unit">{{ unit }}</span>
    </p>
    <p v-if="hint" class="tile-hint">{{ hint }}</p>
  </div>
</template>

<script setup lang="ts">
/** 指标块（统一层）：概览台与存储体检的数字展示，统一字号与层级。 */
withDefaults(
  defineProps<{
    label: string
    value: string | number
    unit?: string
    hint?: string
    tone?: 'default' | 'primary' | 'success' | 'warning' | 'danger'
    wide?: boolean
  }>(),
  { unit: '', hint: '', tone: 'default', wide: false },
)
</script>

<style scoped>
.tile {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
  padding: var(--dpim-space-3) var(--dpim-space-4);
  background: var(--dpim-surface-2);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
  min-width: 0;
}
.tile--wide {
  grid-column: span 2;
}
.tile-label {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tile-value {
  margin: 0;
  font-size: var(--dpim-fs-2xl);
  font-weight: 600;
  line-height: 1.15;
  color: var(--dpim-text);
  font-variant-numeric: tabular-nums;
}
.tile-value--primary {
  color: var(--dpim-primary);
}
.tile-value--success {
  color: var(--dpim-success);
}
.tile-value--warning {
  color: var(--dpim-warning);
}
.tile-value--danger {
  color: var(--dpim-danger);
}
.tile-unit {
  margin-left: var(--dpim-space-1);
  font-size: var(--dpim-fs-md);
  font-weight: 500;
  color: var(--dpim-text-3);
}
.tile-hint {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.4;
  word-break: break-word;
}
</style>
