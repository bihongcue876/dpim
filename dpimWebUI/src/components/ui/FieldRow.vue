<template>
  <div class="field-row">
    <div class="field-label">
      <label :for="controlId">{{ label }}</label>
      <span v-if="hint" class="field-hint">{{ hint }}</span>
    </div>
    <div class="field-control">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 配置行（统一层）：左标签 + 说明，右控件。
 * 运行配置页的所有字段都用它，避免每行各写一套 label 样式。
 */
withDefaults(defineProps<{ label: string; hint?: string; controlId?: string }>(), {
  hint: '',
  controlId: '',
})
</script>

<style scoped>
.field-row {
  display: grid;
  grid-template-columns: minmax(140px, 220px) 1fr;
  gap: var(--dpim-space-3) var(--dpim-space-4);
  align-items: start;
  padding: var(--dpim-space-3) 0;
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
}
.field-row:last-child {
  border-bottom: none;
}
.field-label {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
  padding-top: var(--dpim-space-1);
}
.field-label label {
  font-size: var(--dpim-fs-md);
  font-weight: 500;
  color: var(--dpim-text);
}
.field-hint {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.45;
}
.field-control {
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--dpim-space-2);
}
@media (max-width: 720px) {
  .field-row {
    grid-template-columns: 1fr;
  }
}
</style>
