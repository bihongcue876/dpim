<template>
  <div class="data-table">
    <div class="table-scroll">
      <table class="table">
        <thead>
          <tr>
            <th
              v-for="c in columns"
              :key="c.key"
              :class="[`col-${c.width ?? 'auto'}`, `align-${c.align ?? 'left'}`]"
              scope="col"
            >
              {{ c.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, i) in rows"
            :key="keyOf(row, i)"
            class="row"
            :class="{ 'row--selected': selectedKey !== '' && keyOf(row, i) === selectedKey }"
            @click="emit('row-click', row, i)"
          >
            <td
              v-for="c in columns"
              :key="c.key"
              :class="[`align-${c.align ?? 'left'}`, { 'cell-mono': c.mono }]"
            >
              <slot :name="`cell-${c.key}`" :row="row" :value="valueOf(row, c.key)" :index="i">
                {{ display(valueOf(row, c.key)) }}
              </slot>
            </td>
          </tr>
        </tbody>
      </table>

      <StateBlock
        v-if="rows.length === 0"
        :loading="loading"
        :error="error"
        :empty-text="emptyText"
        :hint="emptyHint"
        fixed-height
      >
        <template #retry><slot name="retry" /></template>
        <template #extra><slot name="empty-extra" /></template>
      </StateBlock>
    </div>

    <footer v-if="total > pageSize" class="table-foot">
      <n-pagination
        :page="Math.floor(offset / pageSize) + 1"
        :page-size="pageSize"
        :item-count="total"
        :page-slot="7"
        @update:page="onPage"
      />
    </footer>
  </div>
</template>

<script setup lang="ts" generic="T">
/**
 * 数据表（统一层）：列表 + 真分页（服务端 offset）+ 行选中 + 三态。
 *
 * 列宽只用 `xs|sm|md|lg|auto` 五档类名，不接受任意像素值——
 * 这样表格永远不需要内联 style（P8）。
 *
 * 泛型 `T` 不约束为 `Record<string, unknown>`：契约里的接口（如 `EventListItem`）
 * 没有索引签名，强行约束会让所有调用点报类型错。单元格取值经 `valueOf` 收敛转换。
 */
import { computed } from 'vue'
import { NPagination } from 'naive-ui'
import StateBlock from './StateBlock.vue'

export interface TableColumn {
  key: string
  label: string
  width?: 'xs' | 'sm' | 'md' | 'lg' | 'auto'
  align?: 'left' | 'right' | 'center'
  mono?: boolean
}

const props = withDefaults(
  defineProps<{
    columns: TableColumn[]
    rows: T[]
    /** 行标识字段名（用于 key 与选中态比较） */
    rowKey?: string
    loading?: boolean
    error?: string
    emptyText?: string
    emptyHint?: string
    selectedKey?: string
    total?: number
    pageSize?: number
    offset?: number
  }>(),
  {
    rowKey: 'id',
    loading: false,
    error: '',
    emptyText: '暂无数据',
    emptyHint: '',
    selectedKey: '',
    total: 0,
    pageSize: 20,
    offset: 0,
  },
)

const emit = defineEmits<{
  'row-click': [row: T, index: number]
  'update:offset': [offset: number]
}>()

function valueOf(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}

function keyOf(row: T, index: number): string {
  const value = valueOf(row, props.rowKey)
  return value === undefined || value === null ? String(index) : String(value)
}

const pageSize = computed(() => props.pageSize)

function onPage(page: number): void {
  emit('update:offset', (page - 1) * pageSize.value)
}

function display(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>

<style scoped>
.data-table {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.table-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  table-layout: fixed;
  font-size: var(--dpim-fs-md);
}
.table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-surface-2);
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
  color: var(--dpim-text-3);
  font-weight: 600;
  font-size: var(--dpim-fs-sm);
  text-align: left;
  white-space: nowrap;
}
.table tbody td {
  padding: var(--dpim-space-2) var(--dpim-space-3);
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
  color: var(--dpim-text);
  vertical-align: top;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row {
  cursor: pointer;
  transition: background-color var(--dpim-dur) ease;
}
.row:hover td {
  background: var(--dpim-surface-hover);
}
.row--selected td {
  background: var(--dpim-primary-soft);
}
.row--selected td:first-child {
  box-shadow: inset 2px 0 0 var(--dpim-primary);
}
.col-xs {
  width: 76px;
}
.col-sm {
  width: 124px;
}
.col-md {
  width: 184px;
}
.col-lg {
  width: 264px;
}
.col-auto {
  width: auto;
}
.align-right {
  text-align: right;
}
.align-center {
  text-align: center;
}
.cell-mono {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
}
.table-foot {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  padding: var(--dpim-space-2) var(--dpim-space-3);
  border-top: var(--dpim-hairline) solid var(--dpim-border);
  background: var(--dpim-surface);
}
</style>
