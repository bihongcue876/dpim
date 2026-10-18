<template>
  <div class="toolbar">
    <div class="toolbar-left"><slot /></div>
    <div class="toolbar-right"><slot name="right" /></div>
  </div>
</template>

<script setup lang="ts">
/**
 * 工具条（统一层）：左筛选 / 右操作，统一高度、间距与换行规则。
 * 仅外观，不含业务逻辑。
 */
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--dpim-space-3);
  flex-wrap: wrap;
  flex-shrink: 0;
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-surface-2);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
}
.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  flex-wrap: wrap;
  min-width: 0;
}
</style>
