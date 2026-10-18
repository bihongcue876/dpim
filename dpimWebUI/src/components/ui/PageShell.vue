<template>
  <section class="page">
    <header class="page-head">
      <div class="page-head-text">
        <p v-if="zone" class="page-zone">{{ zone }}</p>
        <h2 class="page-title">{{ title }}</h2>
        <p v-if="description" class="page-desc">{{ description }}</p>
      </div>
      <div class="page-actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="page-body">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
/**
 * 页面骨架（统一层）：页头（分区 · 标题 · 一句话说明）+ 唯一主操作 + 内容槽。
 *
 * P4 一屏一重点：`actions` 槽只放一个主色按钮，其余操作降级到内容区工具条。
 */
defineProps<{
  title: string
  description?: string
  /** 所属分区名（观测/查阅/写入/维护），来自 router/nav.ts */
  zone?: string
}>()
</script>

<style scoped>
.page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--dpim-space-5) var(--dpim-space-5) var(--dpim-space-4);
  gap: var(--dpim-space-4);
  overflow: hidden;
  background: var(--dpim-surface);
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--dpim-space-4);
  flex-shrink: 0;
}
.page-head-text {
  min-width: 0;
}
.page-zone {
  margin: 0 0 var(--dpim-space-1);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--dpim-text-3);
}
.page-title {
  margin: 0;
  font-size: var(--dpim-fs-xl);
  font-weight: 600;
  color: var(--dpim-text);
  letter-spacing: 0.2px;
  line-height: 1.25;
}
.page-desc {
  margin: var(--dpim-space-1) 0 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text-3);
  line-height: 1.5;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  flex-shrink: 0;
}
.page-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
}
</style>
