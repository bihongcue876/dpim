<template>
  <div class="left-panel">
    <n-tabs type="line" default-value="events" size="small">
      <n-tab-pane name="events" tab="事件列表">
        <n-select
          v-model:value="localEventStatusFilter"
          :options="eventStatusOptions"
          placeholder="状态筛选"
          clearable
          size="small"
          style="margin-bottom:8px"
        />
        <n-select
          v-model:value="localEventTypeFilter"
          :options="eventTypeOptions"
          placeholder="类型筛选"
          clearable
          size="small"
          style="margin-bottom:8px"
        />
        <n-data-table
          :columns="eventColumns"
          :data="eventItems"
          :loading="eventLoading"
          :row-props="(row: any) => ({ style: 'cursor:pointer', onClick: () => $emit('select-event', row.event_id) })"
          size="small"
          :max-height="tableHeight"
        />
        <n-pagination
          v-if="eventTotal > eventLimit"
          :page="eventPage"
          :page-size="eventLimit"
          :item-count="eventTotal"
          @update:page="(p: number) => $emit('event-page', p)"
          size="small"
          style="margin-top:6px"
        />
        <n-empty v-if="!eventLoading && eventItems.length === 0" description="暂无事件" style="padding:40px 0" />
      </n-tab-pane>
      <n-tab-pane name="nodes" tab="节点列表">
        <n-select v-model:value="localNodeTypeFilter" :options="nodeTypeOptions" placeholder="类型筛选" clearable size="small" style="margin-bottom:8px" />
        <n-data-table
          :columns="nodeColumns"
          :data="nodeItems"
          :loading="nodeLoading"
          :row-props="(row: any) => ({ style: 'cursor:pointer', onClick: () => $emit('select-node', row.node_id) })"
          size="small"
          :max-height="tableHeight"
        />
        <n-pagination
          v-if="nodeTotal > nodeLimit"
          :page="nodePage"
          :page-size="nodeLimit"
          :item-count="nodeTotal"
          @update:page="(p: number) => $emit('node-page', p)"
          size="small"
          style="margin-top:6px"
        />
        <n-empty v-if="!nodeLoading && nodeItems.length === 0" description="暂无节点" style="padding:40px 0" />
      </n-tab-pane>
      <n-tab-pane name="search" tab="检索">
        <div class="search-row">
          <n-input v-model:value="localSearchQuery" placeholder="输入关键词" size="small" clearable />
          <n-select v-model:value="localSearchFilter" :options="searchFilterOptions" placeholder="类型" clearable size="small" style="width:100px" />
          <n-button size="small" @click="doSearch" :disabled="!localSearchQuery.trim()">搜索</n-button>
        </div>
        <n-data-table
          :columns="searchColumns"
          :data="searchResults"
          :loading="searchLoading"
          :row-props="(row: any) => ({ style: 'cursor:pointer', onClick: () => $emit('select-node', row.node_id) })"
          size="small"
          :max-height="tableHeight"
        />
        <n-empty v-if="!searchLoading && searchTriggered && searchResults.length === 0" description="无匹配结果" style="padding:40px 0" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { DataTableColumn } from 'naive-ui'
import type { EventListItem, NodeListItem, SearchResult } from '@/api/client'

const props = defineProps<{
  eventItems: EventListItem[]
  eventTotal: number
  eventLimit: number
  eventPage: number
  eventLoading: boolean
  nodeItems: NodeListItem[]
  nodeTotal: number
  nodeLimit: number
  nodePage: number
  nodeLoading: boolean
  searchResults: SearchResult[]
  searchLoading: boolean
}>()

const emit = defineEmits<{
  'select-event': [id: string]
  'select-node': [id: string]
  'event-page': [page: number]
  'node-page': [page: number]
  'search': [query: string, sourceFilter: string]
  'update:event-status': [value: string | undefined]
  'update:event-type': [value: string | undefined]
  'update:node-type': [value: string | undefined]
}>()

// 本地状态：筛选
const localEventStatusFilter = ref<string | undefined>()
const localEventTypeFilter = ref<string | undefined>()
const localNodeTypeFilter = ref<string | undefined>()
const localSearchQuery = ref('')
const localSearchFilter = ref('all')
const searchTriggered = ref(false)

watch(localEventStatusFilter, (v) => emit('update:event-status', v))
watch(localEventTypeFilter, (v) => emit('update:event-type', v))
watch(localNodeTypeFilter, (v) => emit('update:node-type', v))

const tableHeight = computed(() => Math.max(200, window.innerHeight - 160))

function doSearch() {
  if (localSearchQuery.value.trim()) {
    searchTriggered.value = true
    emit('search', localSearchQuery.value, localSearchFilter.value)
  }
}

const eventStatusOptions = [
  { label: 'raw', value: 'raw' },
  { label: 'indexed', value: 'indexed' },
  { label: 'linked', value: 'linked' },
  { label: 'failed', value: 'failed' },
  { label: 'skipped', value: 'skipped' },
]
const eventTypeOptions = [
  { label: 'interaction', value: 'interaction' },
  { label: 'data', value: 'data' },
  { label: 'source', value: 'source' },
]
const nodeTypeOptions = [
  { label: 'system', value: 'system' },
  { label: 'interaction', value: 'interaction' },
  { label: 'data', value: 'data' },
]
const searchFilterOptions = [
  { label: '全部', value: 'all' },
  { label: 'interaction', value: 'interaction' },
  { label: 'data', value: 'data' },
]

const eventColumns: DataTableColumn[] = [
  { title: 'ID', key: 'event_id', width: 160, ellipsis: { tooltip: true } },
  { title: '类型', key: 'event_type', width: 80 },
  { title: '状态', key: 'status', width: 70 },
  { title: '时间', key: 'created_at', width: 150 },
]
const nodeColumns: DataTableColumn[] = [
  { title: 'ID', key: 'node_id', width: 160, ellipsis: { tooltip: true } },
  { title: '标题', key: 'title', ellipsis: { tooltip: true } },
  { title: '类型', key: 'node_type', width: 80 },
  { title: '置信度', key: 'confidence', width: 70 },
]
const searchColumns: DataTableColumn[] = [
  { title: '标题', key: 'title', ellipsis: { tooltip: true } },
  { title: '得分', key: 'score', width: 60 },
  { title: '片段', key: 'snippet', ellipsis: { tooltip: true } },
]
</script>

<style scoped>
.left-panel { height: 100%; padding: 8px; overflow-y: auto; }
.search-row { display: flex; gap: 4px; margin-bottom: 8px; }
</style>
