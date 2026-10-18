<template>
  <section class="card">
    <header v-if="title || $slots.actions" class="card-head">
      <div class="card-head-text">
        <h3 class="card-title">{{ title }}</h3>
        <p v-if="hint" class="card-hint">{{ hint }}</p>
      </div>
      <div class="card-actions"><slot name="actions" /></div>
    </header>
    <div class="card-body" :class="{ 'card-body--flush': flush }"><slot /></div>
  </section>
</template>

<script setup lang="ts">
/**
 * 分区卡片（统一层）：标题 + 说明 + 右上操作 + 内容槽。
 * 概览台、存储体检、运行配置等页面用它分区，避免各页自造容器类名。
 */
withDefaults(
  defineProps<{
    title?: string
    hint?: string
    /** 去掉内容区内边距（表格等自带留白时使用） */
    flush?: boolean
  }>(),
  { title: '', hint: '', flush: false },
)
</script>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  overflow: hidden;
}
.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-3) var(--dpim-space-4);
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
  flex-shrink: 0;
}
.card-title {
  margin: 0;
  font-size: var(--dpim-fs-base);
  font-weight: 600;
  color: var(--dpim-text);
}
.card-hint {
  margin: var(--dpim-space-1) 0 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.45;
}
.card-actions {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  flex-shrink: 0;
}
.card-body {
  flex: 1;
  min-height: 0;
  padding: var(--dpim-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
}
.card-body--flush {
  padding: 0;
}
</style>
