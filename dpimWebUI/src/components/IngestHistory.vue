<template>
  <div class="ingest-history">
    <div class="ih-header">处理历史（最近 {{ items.length }} 条）</div>
    <div v-if="items.length === 0" class="ih-empty">暂无提交记录</div>
    <div v-for="h in items" :key="h.event_id" class="ih-row">
      <span class="ih-time">{{ fmtTime(h.submitted_at) }}</span>
      <span class="ih-id mono" @click="$emit('select', h.event_id)">{{ shortId(h.event_id) }}</span>
      <n-tag size="tiny" :bordered="false" :type="tagType(h)">
        {{ icon(h) }} {{ label(h) }}
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
  /** 连续读取失败次数（非 404）：>0 时这一行明说「状态未知」，不再假装还在处理 */
  read_failures?: number
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

function icon(h: HistoryItem): string {
  // 读取失败优先于状态图标：这一行的状态此刻是「不知道」，不是「处理中」
  if (h.read_failures) return '⚠'
  return {
    linked: '✅', indexed: '⏳', processing: '⟳',
    failed: '❌', skipped: '⊘', timeout: '⚠', removed: '🗑',
  }[h.status] ?? '•'
}

function label(h: HistoryItem): string {
  if (h.status === 'linked') return `已关联 (${h.node_count ?? 0}节点)`
  // 读了 N 次都没读回来 → 说出「状态未知 + 次数」，而不是永远停在「处理中...」
  if (h.read_failures) return `状态未知（${h.read_failures} 次读取失败）`
  return {
    indexed: '已索引', processing: '处理中...', failed: '处理失败',
    skipped: '已跳过', timeout: '处理超时', removed: '事件已删除',
  }[h.status] ?? h.status
}

function tagType(h: HistoryItem): 'success' | 'info' | 'warning' | 'error' | 'default' {
  if (h.read_failures) return 'warning'
  return {
    linked: 'success', indexed: 'info', processing: 'warning',
    failed: 'error', skipped: 'default', timeout: 'warning', removed: 'default',
  }[h.status] as 'success' | 'info' | 'warning' | 'error' | 'default'
}
</script>

<style scoped>
.ingest-history { display: flex; flex-direction: column; }
.ih-header { font-size: var(--dpim-fs-md); font-weight: 600; margin-bottom: var(--dpim-space-2); color: var(--dpim-text); }
.ih-empty { font-size: var(--dpim-fs-sm); color: var(--dpim-text-3); padding: var(--dpim-space-3) 0; text-align: center; }
.ih-row {
  display: flex; align-items: center; gap: var(--dpim-space-3);
  padding: var(--dpim-space-1);
  font-size: var(--dpim-fs-sm);
  border-bottom: 1px dashed var(--dpim-border);
}
.ih-row:last-child { border-bottom: none; }
.ih-time { color: var(--dpim-text-3); flex-shrink: 0; font-family: 'Cascadia Code', Consolas, monospace; font-size: var(--dpim-fs-xs); }
.ih-id { cursor: pointer; color: var(--dpim-text); text-decoration: underline dotted; }
.ih-id:hover { color: var(--dpim-primary); }
.mono { font-family: 'Cascadia Code', Consolas, monospace; }
</style>
