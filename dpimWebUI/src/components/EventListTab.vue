<template>
  <div class="event-tab">
    <!-- 左侧：事件列表 -->
    <div class="event-left">
      <div class="event-toolbar">
        <n-select v-model:value="filterType" :options="typeOpts" placeholder="类型" clearable size="tiny" style="width:90px" @update:value="load" />
        <n-select v-model:value="filterStatus" :options="statusOpts" placeholder="状态" clearable size="tiny" style="width:90px" @update:value="load" />
        <n-button size="tiny" @click="showNewModal = true">新建</n-button>
        <n-button v-if="selectedIds.size > 0" size="tiny" type="error" @click="onDeleteSelected">删除选中（{{ selectedIds.size }}）</n-button>
        <div class="toolbar-spacer"></div>
        <span class="toolbar-count">共 {{ total }} 条</span>
        <n-button size="tiny" quaternary circle @click="load()" :loading="loading" title="刷新列表">
          <template #icon><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M1 4v6h6M23 20v-6h-6"/><path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15"/></svg></template>
        </n-button>
      </div>
      <div class="event-table-wrap">
        <n-spin :show="loading" size="small">
          <div v-for="ev in items" :key="ev.event_id"
            class="event-row"
            :class="{ active: ev.event_id === selectedId }"
            @click="onSelectRow(ev.event_id)">
            <n-checkbox size="tiny" :checked="selectedIds.has(ev.event_id)" @click.stop @update:checked="toggleSelect(ev.event_id)" style="margin-right:2px" />
            <span class="ev-time">{{ ev.created_at.slice(5,16) }}</span>
            <n-tag size="tiny" :bordered="false" :type="tagType(ev.event_type)">{{ ev.event_type }}</n-tag>
            <span class="ev-content">{{ ev.raw_content.slice(0,50) }}{{ ev.raw_content.length > 50 ? '…' : '' }}</span>
            <n-tag size="tiny" :bordered="false" :type="statusTagType(ev.status)">{{ ev.status }}</n-tag>
          </div>
          <n-empty v-if="!loading && items.length === 0" description="暂无事件" size="small" style="padding:40px" />
        </n-spin>
      </div>
      <n-pagination v-if="total > limit" :page="page" :page-size="limit" :item-count="total" @update:page="onPage" size="tiny" style="margin-top:4px" />
    </div>
    <!-- 右侧：详情 + 操作 -->
    <div class="event-right">
      <n-spin :show="loadingDetail" size="small">
      <template v-if="detail">
        <div class="detail-scroll">
          <h4>事件详情</h4>
          <n-descriptions size="small" :column="1" label-placement="left">
            <n-descriptions-item label="ID">{{ detail.event_id }}</n-descriptions-item>
            <n-descriptions-item label="类型">{{ detail.event_type }}</n-descriptions-item>
            <n-descriptions-item label="状态">
              <div style="display:flex;align-items:center;gap:6px">
                <n-tag size="tiny" :bordered="false" :type="statusTagType(detail.status as string)">{{ detail.status }}</n-tag>
                <n-button v-if="detail.status === 'failed'" size="tiny" @click="onRetry(detail.event_id as string)">重试</n-button>
              </div>
            </n-descriptions-item>
            <n-descriptions-item label="时间">{{ detail.created_at }}</n-descriptions-item>
            <n-descriptions-item label="哈希">
              <span class="mono-text">{{ String(detail.content_hash || '').slice(0, 16) }}</span>
            </n-descriptions-item>
            <n-descriptions-item v-if="detail.graph_refs" label="图关联">
              <span class="mono-text">{{ JSON.stringify(detail.graph_refs) }}</span>
            </n-descriptions-item>
            <n-descriptions-item label="内容">
              <template v-if="editing">
                <n-input v-model:value="editContent" type="textarea" :rows="4" />
              </template>
              <div v-else class="raw-content">{{ detail.raw_content }}</div>
            </n-descriptions-item>
          </n-descriptions>
          <div class="detail-actions">
            <template v-if="editing">
              <n-button size="small" @click="cancelEdit">取消</n-button>
              <n-button size="small" type="primary" @click="saveEdit" :loading="saving">保存</n-button>
            </template>
            <template v-else>
              <n-button size="small" @click="startEdit">编辑事件</n-button>
              <n-button size="small" type="error" @click="onDelete(detail.event_id as string)">删除事件</n-button>
              <n-popover trigger="hover" placement="top">
                <template #trigger>
                  <n-button size="small" :disabled="!canGenerate" :loading="generating" @click="onGenerate">生成知识</n-button>
                </template>
                <span style="font-size:12px">{{ generateHint }}</span>
              </n-popover>
            </template>
          </div>
        </div>
      </template>
      <n-empty v-else-if="!loadingDetail" description="选中一条事件查看详情" size="small" style="padding:60px" />
      </n-spin>
    </div>
    <!-- 新建事件模态框 -->
    <n-modal v-model:show="showNewModal" title="新建事件" preset="card" style="width:500px">
      <n-input v-model:value="newContent" type="textarea" placeholder="事件内容" :rows="4" />
      <n-select v-model:value="newType" :options="createTypeOpts" placeholder="类型" style="margin-top:8px" />
      <template #footer>
        <n-button size="small" @click="showNewModal = false">取消</n-button>
        <n-button size="small" type="primary" :disabled="!newContent.trim()" :loading="creating" @click="doCreate">创建</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { createDiscreteApi } from 'naive-ui'
import type { EventListItem } from '@/api/client'
import * as api from '@/api/client'

const { message, dialog } = createDiscreteApi(['message', 'dialog'])

const props = defineProps<{
  validate: () => Promise<boolean>
  onCommitted: () => Promise<void>
}>()

const items = ref<EventListItem[]>([])
const total = ref(0)
const limit = 20
const page = ref(1)
const loading = ref(false)
const selectedId = ref<string | null>(null)
const detail = ref<Record<string, unknown> | null>(null)
const loadingDetail = ref(false)
const filterType = ref<string | undefined>()
const filterStatus = ref<string | undefined>()
const showNewModal = ref(false)
const newContent = ref('')
const newType = ref('auto')
const editing = ref(false)
const editContent = ref('')
const saving = ref(false)
const creating = ref(false)
const generating = ref(false)
const selectedIds = ref(new Set<string>())

function toggleSelect(id: string) {
  const s = selectedIds.value
  if (s.has(id)) s.delete(id); else s.add(id)
  // trigger reactivity by replacing the Set
  selectedIds.value = new Set(s)
}

const typeOpts = [
  { label: '全部', value: undefined },
  { label: 'interaction', value: 'interaction' },
  { label: 'data', value: 'data' },
  { label: 'source', value: 'source' },
]
const createTypeOpts = [
  { label: '自动识别', value: 'auto' },
  { label: 'interaction', value: 'interaction' },
  { label: 'data', value: 'data' },
  { label: 'source', value: 'source' },
]
const statusOpts = [
  { label: '全部', value: undefined },
  { label: 'raw', value: 'raw' }, { label: 'indexed', value: 'indexed' },
  { label: 'linked', value: 'linked' }, { label: 'failed', value: 'failed' },
  { label: 'skipped', value: 'skipped' },
]

function tagType(t: string) {
  if (t === 'interaction') return 'success'
  if (t === 'data') return 'warning'
  return 'info'
}

function statusTagType(s: string) {
  if (s === 'linked') return 'success'
  if (s === 'failed') return 'error'
  if (s === 'indexed') return 'info'
  if (s === 'skipped') return 'warning'
  return 'default'
}

async function onRetry(eventId: string) {
  try {
    await api.putEventStatus(eventId, 'indexed')
    await props.onCommitted()
    message.success('已重置为 indexed，管线开始处理')
    await onSelectRow(eventId)
    await load()
  } catch (e: any) {
    message.error('重试失败: ' + (e.message || '未知错误'))
  }
}

async function load(p = 1) {
  loading.value = true
  try {
    const res = await api.listEvents({ status: filterStatus.value, type: filterType.value, limit, offset: (p - 1) * limit })
    items.value = res.items
    total.value = res.total
    page.value = p
  } catch { /* ignore */ }
  finally { loading.value = false }
}
function onPage(p: number) { load(p) }

async function onSelectRow(eventId: string) {
  selectedId.value = eventId
  editing.value = false
  loadingDetail.value = true
  try {
    detail.value = await api.getEvent(eventId)
  } catch { detail.value = null }
  finally { loadingDetail.value = false }
}

function startEdit() {
  if (!detail.value) return
  editContent.value = String(detail.value.raw_content ?? '')
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  editContent.value = ''
}

async function saveEdit() {
  if (!detail.value || !editContent.value.trim()) return
  const ok = await props.validate()
  if (!ok) {
    // key 过期：刷新数据但保留编辑内容，让用户重试
    const savedEdit = editContent.value
    await onSelectRow(detail.value.event_id as string)
    editContent.value = savedEdit
    editing.value = true
    message.warning('数据已被其他人修改，已更新最新内容，请复查后重新保存')
    return
  }
  saving.value = true
  try {
    await api.putEvent(detail.value.event_id as string, editContent.value)
    await props.onCommitted()
    editing.value = false
    editContent.value = ''
    message.success('事件内容已更新')
    await onSelectRow(detail.value.event_id as string)
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || '未知错误'))
  }
  finally { saving.value = false }
}

// 跨标签导航：从「信息传入」跳转定位到某条事件
const onFocusEvent = ((e: Event) => {
  const eventId = (e as CustomEvent).detail?.event_id as string | undefined
  if (!eventId) return
  filterType.value = undefined
  filterStatus.value = undefined
  onSelectRow(eventId)
  load()
}) as EventListener

onMounted(() => {
  load()
  window.addEventListener('dpim:focus-event', onFocusEvent)
})
onUnmounted(() => {
  window.removeEventListener('dpim:focus-event', onFocusEvent)
})

async function onGenerate() {
  // 触发补偿：把 raw/indexed 积压事件重新入队走 Agent 管线生成知识
  // （本条若为 raw/indexed 也会被包含；failed 请先用「重试」）
  generating.value = true
  try {
    await api.compensate()
    message.success('已触发补偿，raw/indexed 积压事件开始重新处理')
  } catch (e: any) {
    message.error('触发失败: ' + (e?.message || '未知错误'))
  } finally {
    generating.value = false
  }
}

// 生成知识 = 补偿 raw/indexed 积压事件：linked 已处理、failed 需先重试、source 不构图
const canGenerate = computed(() => {
  const s = String(detail.value?.status ?? '')
  const t = String(detail.value?.event_type ?? '')
  return t !== 'source' && s !== 'linked' && s !== 'failed'
})
const generateHint = computed(() => {
  const s = String(detail.value?.status ?? '')
  const t = String(detail.value?.event_type ?? '')
  if (t === 'source') return 'source 类型仅存储，不进入图谱'
  if (s === 'linked') return '本条已生成知识，无需处理'
  if (s === 'failed') return '失败事件请先点「重试」重新入队'
  return '将 raw / indexed 积压事件重新入队，走 Agent 管线处理'
})

async function onDelete(eventId: string) {
  dialog.warning({
    title: '确认删除',
    content: '确认删除此事件？关联节点将同步更新源证状态。',
    positiveText: '确认删除',
    negativeText: '取消',
    async onPositiveClick() {
      const ok = await props.validate()
      if (!ok) {
        message.warning('数据已变更，已刷新列表，请重新点击删除')
        await load()
        return
      }
      try {
        await api.deleteEvent(eventId)
        await props.onCommitted()
        message.success('事件已删除')
        selectedId.value = null
        detail.value = null
        await load()
      } catch (e: any) {
        message.error('删除失败: ' + (e.message || '未知错误'))
      }
    },
  })
}

async function onDeleteSelected() {
  const ids = Array.from(selectedIds.value)
  if (ids.length === 0) return
  const ok = await props.validate()
  if (!ok) {
    message.warning('数据已变更，已刷新，请重新选择')
    selectedIds.value = new Set()
    await load()
    return
  }
  dialog.warning({
    title: '批量删除事件',
    content: `确认删除选中的 ${ids.length} 条事件？`,
    positiveText: '确认删除',
    negativeText: '取消',
    async onPositiveClick() {
      let fail = 0
      for (const id of ids) {
        try {
          await api.deleteEvent(id)
        } catch { fail++ }
      }
      await props.onCommitted()
      selectedIds.value = new Set()
      if (fail === 0) {
        message.success(`${ids.length} 条事件已删除`)
      } else {
        message.warning(`删除完成：${ids.length - fail} 成功，${fail} 失败`)
      }
      selectedId.value = null
      detail.value = null
      await load()
    },
  })
}

async function doCreate() {
  if (!newContent.value.trim()) return
  creating.value = true
  try {
    await api.ingest(newContent.value, newType.value === 'auto' ? undefined : newType.value)
    await props.onCommitted()
    showNewModal.value = false
    newContent.value = ''
    newType.value = 'auto'
    message.success('事件已创建')
    await load()
  } catch (e: any) {
    message.error('创建失败: ' + (e.message || '未知错误'))
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.event-tab { flex: 1; display: flex; min-height: 0; }
.event-left {
  width: 36%; display: flex; flex-direction: column;
  padding: 12px 14px; gap: 8px;
  border-right: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  background: var(--dpim-surface, #161b22);
}
.event-toolbar { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.toolbar-spacer { flex: 1; }
.toolbar-count { font-size: 11px; color: var(--dpim-text-3, #7c8694); white-space: nowrap; }
.event-table-wrap {
  flex: 1; overflow-y: auto; min-height: 0;
  border: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  border-radius: var(--dpim-radius-sm, 8px);
  background: var(--dpim-bg, #0e1217);
  padding: 4px;
}
.event-row {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px; font-size: 12px;
  cursor: pointer; border-radius: 6px; border-left: 2px solid transparent;
  transition: background 0.12s ease;
}
.event-row:hover { background: var(--dpim-surface-hover, rgba(255,255,255,0.04)); }
.event-row.active { background: var(--dpim-primary-soft, rgba(91,140,255,0.14)); border-left-color: var(--dpim-primary, #5b8cff); }
.ev-time { color: var(--dpim-text-3, #7c8694); width: 84px; flex-shrink: 0; font-family: 'Cascadia Code', Consolas, monospace; font-size: 11px; }
.ev-content { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--dpim-text-2, #aab4c0); }
.event-right { flex: 1; display: flex; flex-direction: column; padding: 16px 20px; overflow: hidden; }
.detail-scroll { flex: 1; overflow-y: auto; min-height: 0; }
.detail-actions { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
.raw-content {
  font-size: 13px; line-height: 1.7; white-space: pre-wrap; max-height: 320px; overflow-y: auto;
  background: var(--dpim-bg, #0e1217); border: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  padding: 10px 12px; border-radius: var(--dpim-radius-sm, 8px);
  color: var(--dpim-text-2, #aab4c0);
}
.mono-text { font-family: 'Cascadia Code', Consolas, monospace; font-size: 12px; color: var(--dpim-text-3, #7c8694); }
h4 { margin: 0 0 12px; font-size: 14px; color: var(--dpim-text, #e6edf3); }
</style>
