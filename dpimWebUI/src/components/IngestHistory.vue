<template>
  <div class="ingest-history">
    <div class="ih-header">处理历史（最近 {{ items.length }} 条）</div>
    <div v-if="items.length === 0" class="ih-empty">暂无提交记录</div>
    <div v-for="h in items" :key="h.event_id" class="ih-row">
      <span class="ih-time">{{ fmtTime(h.submitted_at) }}</span>
      <span class="ih-id mono" @click="$emit('select', h.event_id)">{{ shortId(h.event_id) }}</span>
      <n-tag size="tiny" :bordered="false" :type="tagType(h.status)">
        {{ icon(h.status) }} {{ label(h) }}
      </n-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
interface HistoryItem {
  event_id: string
  submitted_at: string
  status: string
  node_count?: number
}

defineProps<{
  items: HistoryItem[]
}>()

defineEmits<{
  (e: 'select', eventId: string): void
}>()

function shortId(id: string): string {
  return id.length > 16 ? id.slice(0, 16) + '…' : id
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toTimeString().slice(0, 8)
}

function icon(status: string): string {
  return {
    linked: '✅', indexed: '⏳', processing: '⟳',
    failed: '❌', skipped: '⊘', timeout: '⚠', removed: '🗑',
  }[status] ?? '•'
}

function label(h: HistoryItem): string {
  if (h.status === 'linked') return `已关联 (${h.node_count ?? 0}节点)`
  return {
    indexed: '已索引', processing: '处理中...', failed: '处理失败',
    skipped: '已跳过', timeout: '处理超时', removed: '事件已删除',
  }[h.status] ?? h.status
}

function tagType(status: string): 'success' | 'info' | 'warning' | 'error' | 'default' {
  return {
    linked: 'success', indexed: 'info', processing: 'warning',
    failed: 'error', skipped: 'default', timeout: 'warning', removed: 'default',
  }[status] as 'success' | 'info' | 'warning' | 'error' | 'default'
}
</script>

<style scoped>
.ingest-history { display: flex; flex-direction: column; }
.ih-header { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--dpim-text, #e6edf3); }
.ih-empty { font-size: 12px; color: var(--dpim-text-3, #7c8694); padding: 12px 0; text-align: center; }
.ih-row {
  display: flex; align-items: center; gap: 12px;
  padding: 7px 4px; font-size: 12px;
  border-bottom: 1px dashed var(--dpim-border, rgba(255,255,255,0.07));
}
.ih-row:last-child { border-bottom: none; }
.ih-time { color: var(--dpim-text-3, #7c8694); flex-shrink: 0; font-family: 'Cascadia Code', Consolas, monospace; font-size: 11px; }
.ih-id { cursor: pointer; color: var(--dpim-text, #e6edf3); text-decoration: underline dotted; }
.ih-id:hover { color: var(--dpim-primary, #5b8cff); }
.mono { font-family: 'Cascadia Code', Consolas, monospace; }
</style>
