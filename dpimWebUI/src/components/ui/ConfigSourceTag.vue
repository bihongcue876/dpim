<template>
  <span v-if="envName" class="chip chip--lock">由环境变量 {{ envName }} 决定（界面不可改）</span>
  <span v-else-if="source === 'file'" class="chip chip--file">已存 {{ fileLabel }}</span>
  <span v-else-if="source === 'default'" class="chip chip--muted">默认值</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
/**
 * 配置来源标签（统一层，v1.36）：回答「这个值到底来自哪里」。
 *
 * `GET /settings` 的 `config_sources[字段]` 有三种取值：
 * - `env:DPIM_X` —— 环境变量顶掉（保存也无效），表单控件必须置灰 + 明示变量名；
 *   这正是「我改了但没生效」的根源，所以锁定态必须**看得见**。
 * - `file` —— 持久化在 dpim.json 里（重启后仍在）。
 * - `default` —— 内置默认值（从未改过）。
 *
 * 只读展示，不含逻辑；颜色/间距一律走 `--dpim-*` 令牌。
 */
const props = withDefaults(
  defineProps<{
    /** config_sources[字段] 原文；缺省 = 后端未上报该字段来源（不渲染） */
    source?: string
    /** 持久化文件名（后端 config_file 的基名，用于「已存 …」文案） */
    fileLabel?: string
  }>(),
  { source: '', fileLabel: 'dpim.json' },
)

/** `env:DPIM_X` 的 DPIM_X；非 env 锁定返回空串（来源在挂载后才到达，须响应式） */
const envName = computed(() =>
  props.source.startsWith('env:') ? props.source.slice('env:'.length) : '',
)
</script>

<style scoped>
.chip {
  padding: 0 var(--dpim-space-2);
  border: var(--dpim-hairline) solid transparent;
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  line-height: 1.7;
  white-space: nowrap;
}
.chip--lock {
  background: var(--dpim-warning-soft);
  border-color: var(--dpim-warning);
  color: var(--dpim-warning);
}
.chip--file,
.chip--muted {
  background: var(--dpim-surface-2);
  border-color: var(--dpim-border);
  color: var(--dpim-text-3);
}
</style>
