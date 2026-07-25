<template>
  <div class="event-tab">
    <!-- 左侧：事件列表 -->
    <div class="event-left">
      <div class="event-toolbar">
        <n-select v-model:value="filterType" :options="typeOpts" placeholder="类型" clearable size="tiny" style="width:90px" @update:value="load" />
        <n-select v-model:value="filterStatus" :options="statusOpts" placeholder="状态" clearable size="tiny" style="width:90px" @update:value="load" />
        <n-button size="tiny" @click="showNewModal = true">新建事件</n-button>
      </div>
      <div class="event-table-wrap">
        <div v-for="ev in items" :key="ev.event_id"
          class="event-row"
          :class="{ active: ev.event_id === selectedId }"
          @click="onSelectRow(ev.event_id)">
          <span class="ev-time">{{ ev.created_at.slice(5,16) }}</span>
          <n-tag size="tiny" :bordered="false" :type="tagType(ev.event_type)">{{ ev.event_type }}</n-tag>
          <span class="ev-content">{{ ev.raw_content.slice(0,50) }}{{ ev.raw_content.length > 50 ? '…' : '' }}</span>
          <n-tag size="tiny" :bordered="false">{{ ev.status }}</n-tag>
        </div>
        <n-empty v-if="!loading && items.length === 0" description="暂无事件" size="small" style="padding:40px" />
      </div>
      <n-pagination v-if="total > limit" :page="page" :page-size="limit" :item-count="total" @update:page="onPage" size="tiny" style="margin-top:4px" />
    </div>
    <!-- 右侧：详情 + 操作 -->
    <div class="event-right">
      <template v-if="detail">
        <div class="detail-scroll">
          <h4>事件详情</h4>
          <n-description size="small" :column="1" label-placement="left">
            <n-description-item label="ID">{{ detail.event_id }}</n-description-item>
            <n-description-item label="类型">{{ detail.event_type }}</n-description-item>
            <n-description-item label="状态">{{ detail.status }}</n-description-item>
            <n-description-item label="时间">{{ detail.created_at }}</n-description-item>
            <n-description-item label="内容">
              <div class="raw-content">{{ detail.raw_content }}</div>
            </n-description-item>
          </n-description>
          <div class="detail-actions">
            <n-button size="small" type="error" @click="onDelete(detail.event_id)">删除事件</n-button>
            <n-button size="small" :disabled="detail.event_type === 'source'" @click="onGenerate">生成知识</n-button>
          </div>
        </div>
      </template>
      <n-empty v-else description="选中一条事件查看详情" size="small" style="padding:60px" />
    </div>
    <!-- 新建事件模态框 -->
    <n-modal v-model:show="showNewModal" title="新建事件" preset="card" style="width:500px">
      <n-input v-model:value="newContent" type="textarea" placeholder="事件内容" :rows="4" />
      <n-select v-model:value="newType" :options="typeOpts" placeholder="类型" style="margin-top:8px" />
      <template #footer>
        <n-button size="small" @click="showNewModal = false">取消</n-button>
        <n-button size="small" type="primary" :disabled="!newContent.trim()" @click="doCreate">创建</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { EventListItem } from '@/api/client'
import * as api from '@/api/client'

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
const filterType = ref<string | undefined>()
const filterStatus = ref<string | undefined>()
const showNewModal = ref(false)
const newContent = ref('')
const newType = ref('auto')

const typeOpts = [
  { label: '全部', value: undefined },
  { label: 'interaction', value: 'interaction' },
  { label: 'data', value: 'data' },
  { label: 'source', value: 'source' },
]
const statusOpts = [
  { label: '全部', value: undefined },
  { label: 'raw', value: 'raw' }, { label: 'indexed', value: 'indexed' },
  { label: 'linked', value: 'linked' }, { label: 'failed', value: 'failed' },
]

function tagType(t: string) {
  if (t === 'interaction') return 'success'
  if (t === 'data') return 'warning'
  return 'info'
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
  try {
    detail.value = await api.getEvent(eventId)
  } catch { /* ignore */ }
}

onMounted(load)

function onGenerate() {
  // TODO: 调用图构建 Agent，需 Agent 提示词就绪后启用
}

async function onDelete(eventId: string) {
  const ok = await props.validate()
  if (!ok) {
    await load()
    return
  }
  try {
    await api.deleteEvent(eventId)
    await props.onCommitted()
    await load()
  } catch (e: any) { /* ignore */ }
}

async function doCreate() {
  if (!newContent.value.trim()) return
  try {
    await api.ingest(newContent.value, newType.value === 'auto' ? undefined : newType.value)
    showNewModal.value = false
    newContent.value = ''
    newType.value = 'auto'
    await load()
  } catch { /* ignore */ }
}
</script>

<style scoped>
.event-tab { display: flex; height: 100%; }
.event-left { width: 35%; border-right: 1px solid var(--n-border-color); display: flex; flex-direction: column; padding: 8px; }
.event-toolbar { display: flex; gap: 4px; margin-bottom: 6px; flex-wrap: wrap; }
.event-table-wrap { flex: 1; overflow-y: auto; }
.event-row {
  display: flex; align-items: center; gap: 6px; padding: 4px 6px; font-size: 12px; cursor: pointer; border-radius: 3px;
}
.event-row:hover { background: rgba(255,255,255,0.05); }
.event-row.active { background: rgba(81,162,255,0.2); }
.ev-time { color: var(--n-text-color-3); width: 80px; flex-shrink: 0; }
.ev-content { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.event-right { flex: 1; display: flex; flex-direction: column; padding: 12px; overflow: hidden; }
.detail-scroll { overflow-y: auto; height: 100%; }
.detail-actions { display: flex; gap: 8px; margin-top: 16px; }
.raw-content { font-size: 13px; line-height: 1.6; white-space: pre-wrap; max-height: 300px; overflow-y: auto; background: rgba(0,0,0,0.15); padding: 8px; border-radius: 4px; }
h4 { margin: 0 0 8px; font-size: 14px; }
</style>
