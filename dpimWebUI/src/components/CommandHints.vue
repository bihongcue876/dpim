<template>
  <ul v-if="items.length" class="cmd-hints" role="listbox" aria-label="指令候选">
    <li
      v-for="(c, i) in items"
      :key="c.name"
      :class="{ active: i === activeIndex }"
      role="option"
      :aria-selected="i === activeIndex"
      @mousedown.prevent="$emit('select', c)"
    >
      <span class="cmd-name">{{ c.name }}</span>
      <span class="cmd-args mono">{{ c.args }}</span>
      <span class="cmd-desc">{{ c.desc }}<template v-if="c.needsAI"> · 需 AI</template></span>
    </li>
  </ul>
</template>

<script setup lang="ts">
import type { CommandCandidate } from '@/api/commands'

defineProps<{
  items: CommandCandidate[]
  activeIndex: number
}>()

defineEmits<{ (e: 'select', c: CommandCandidate): void }>()
</script>

<style scoped>
.cmd-hints {
  position: absolute;
  bottom: calc(100% - 6px);
  left: 0;
  right: 0;
  z-index: 20;
  margin: 0;
  padding: 4px;
  list-style: none;
  background: var(--dpim-surface-raised, #1c2129);
  border: 1px solid var(--dpim-border, rgba(255, 255, 255, 0.12));
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  max-height: 260px;
  overflow-y: auto;
}
.cmd-hints li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 12.5px;
  line-height: 1.5;
}
.cmd-hints li.active {
  background: var(--dpim-primary-soft, rgba(88, 166, 255, 0.12));
}
.cmd-name {
  color: var(--dpim-primary, #58a6ff);
  font-family: 'Cascadia Code', Consolas, monospace;
  font-weight: 600;
  flex-shrink: 0;
}
.cmd-args {
  color: var(--dpim-text-3, #7c8694);
  flex-shrink: 0;
}
.cmd-desc {
  color: var(--dpim-text-2, #9aa4b2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mono {
  font-family: 'Cascadia Code', Consolas, monospace;
}
</style>
