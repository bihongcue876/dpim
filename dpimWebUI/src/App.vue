<template>
  <n-config-provider :theme="darkTheme" :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-layout class="app-layout">
        <TopBar :hash-status="hashStatus" @refresh-hash="refreshHash" />
        <n-layout-content class="app-content">
          <!-- 三栏布局 -->
          <LeftPanel
            :event-items="eventItems"
            :event-total="eventTotal"
            :event-limit="eventLimit"
            :event-page="eventPage"
            :event-loading="eventLoading"
            :node-items="nodeItems"
            :node-total="nodeTotal"
            :node-limit="nodeLimit"
            :node-page="nodePage"
            :node-loading="nodeLoading"
            :search-results="searchResults"
            :search-loading="searchLoading"
            @select-event="onSelectEvent"
            @select-node="onSelectNode"
            @event-page="onEventPage"
            @node-page="onNodePage"
            @search="onSearch"
            @update:event-status="onEventStatusFilter"
            @update:event-type="onEventTypeFilter"
            @update:node-type="onNodeTypeFilter"
          />
          <div class="center-panel">
            <GraphCanvas
              :nodes="graphNodes"
              :edges="graphEdges"
              :highlight-node-id="highlightNodeId"
              @select-node="onSelectNode"
              @double-click-node="onDoubleClickNode"
            />
          </div>
          <RightPanel
            :view="rightView"
            :locked="isLocked"
            :event="selectedEvent"
            :node="selectedNode"
            :settings="settings"
            :saved-hint="savedHint"
            @delete-event="onDeleteEvent"
            @retry-event="onRetryEvent"
            @save-node="onSaveNode"
            @delete-node="onDeleteNode"
            @save-settings="onSaveSettings"
          />
        </n-layout-content>
        <StatusBar
          :connected="connected"
          :ai-available="aiAvailable"
          :total-events="totalEvents"
          :total-nodes="totalNodes"
        />
      </n-layout>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { darkTheme, zhCN, dateZhCN, useMessage } from 'naive-ui'
import type { MessageApi } from 'naive-ui'

import TopBar from '@/components/TopBar.vue'
import StatusBar from '@/components/StatusBar.vue'
import LeftPanel from '@/components/LeftPanel.vue'
import RightPanel from '@/components/RightPanel.vue'
import GraphCanvas from '@/components/GraphCanvas.vue'
import { useStateHash } from '@/composables/useStateHash'
import * as api from '@/api/client'
import type { NodeDetail, EdgeInfo, SettingsResponse } from '@/api/client'

const message = useMessage() as MessageApi

// ── Hash lock ──
const { isLocked, hashStatus, refresh } = useStateHash()
async function refreshHash() {
  await refresh()
  if (!isLocked.value) message.success('数据一致，已解锁')
  else message.warning('数据已变更，请刷新后再操作')
}

// ── Health / status ──
const connected = ref(true)
const aiAvailable = ref(false)
const totalEvents = ref(0)
const totalNodes = ref(0)

async function loadHealth() {
  try {
    const h = await api.getHealth()
    connected.value = true
    aiAvailable.value = h.ai_available
    totalEvents.value = h.layers.event_line.total_events ?? 0
    totalNodes.value = h.layers.knowledge_graph.total_nodes ?? 0
  } catch {
    connected.value = false
  }
}

// ── Events ──
const eventItems = ref<api.EventListItem[]>([])
const eventTotal = ref(0)
const eventLimit = 20
const eventPage = ref(1)
const eventLoading = ref(false)
const eventStatusFilter = ref<string | undefined>()
const eventTypeFilter = ref<string | undefined>()

async function loadEvents(page = 1) {
  eventLoading.value = true
  try {
    const res = await api.listEvents({
      status: eventStatusFilter.value,
      type: eventTypeFilter.value,
      limit: eventLimit,
      offset: (page - 1) * eventLimit,
    })
    eventItems.value = res.items
    eventTotal.value = res.total
    eventPage.value = page
  } catch (e: any) { message.error(e.message) }
  finally { eventLoading.value = false }
}

function onEventPage(p: number) { loadEvents(p) }
function onNodePage(p: number) { loadNodes(p) }

// ── Nodes ──
const nodeItems = ref<api.NodeListItem[]>([])
const nodeTotal = ref(0)
const nodeLimit = 20
const nodePage = ref(1)
const nodeLoading = ref(false)
const nodeTypeFilterValue = ref<string | undefined>()
const graphNodes = ref<api.NodeListItem[]>([])
const graphEdges = ref<EdgeInfo[]>([])

async function loadNodes(page = 1) {
  nodeLoading.value = true
  try {
    const res = await api.listNodes({
      type: nodeTypeFilterValue.value,
      limit: nodeLimit,
      offset: (page - 1) * nodeLimit,
    })
    nodeItems.value = res.items
    nodeTotal.value = res.total
    nodePage.value = page
  } catch (e: any) { message.error(e.message) }
  finally { nodeLoading.value = false }
}

async function loadGraphData() {
  try {
    const all = await api.listNodes({ limit: 200 })
    graphNodes.value = all.items
    if (all.items.length > 0) {
      const first = await api.getNode(all.items[0].node_id)
      graphEdges.value = first.edges
    }
  } catch { /* empty graph is fine */ }
}

// ── Search ──
const searchResults = ref<api.SearchResult[]>([])
const searchLoading = ref(false)

let lastSearchFilter = 'all'

async function onSearch(q: string, sourceFilter: string) {
  if (!q.trim()) return
  lastSearchFilter = sourceFilter
  searchLoading.value = true
  try {
    const res = await api.query({ query: q, source_filter: sourceFilter })
    searchResults.value = res.results
  } catch (e: any) { message.error(e.message) }
  finally { searchLoading.value = false }
}

// ── Filters ──
function onEventStatusFilter(val: string | undefined) { eventStatusFilter.value = val; loadEvents(1) }
function onEventTypeFilter(val: string | undefined) { eventTypeFilter.value = val; loadEvents(1) }
function onNodeTypeFilter(val: string | undefined) { nodeTypeFilterValue.value = val; loadNodes(1) }

// ── Right panel ──
const rightView = ref('config')
const selectedEvent = ref<Record<string, unknown> | null>(null)
const selectedNode = ref<NodeDetail | null>(null)
const highlightNodeId = ref<string | null>(null)
const settings = ref<SettingsResponse | null>(null)
const savedHint = ref('')

async function onSelectEvent(id: string) {
  rightView.value = 'event'
  try {
    selectedEvent.value = await api.getEvent(id)
  } catch (e: any) { message.error(e.message) }
}

async function onSelectNode(id: string) {
  rightView.value = 'node'
  highlightNodeId.value = id
  try {
    selectedNode.value = await api.getNode(id)
  } catch (e: any) { message.error(e.message) }
}

function onDoubleClickNode(id: string) {
  // Center graph on this node — handled by GraphCanvas internals
  onSelectNode(id)
}

async function onDeleteEvent(id: string) {
  try {
    await api.deleteEvent(id)
    message.success('事件已删除')
    loadEvents(eventPage.value)
    loadHealth()
  } catch (e: any) { message.error(e.message) }
}

async function onRetryEvent(id: string) {
  try {
    await api.putEventStatus(id, 'indexed')
    message.success('已重置为 indexed')
    loadEvents(eventPage.value)
  } catch (e: any) { message.error(e.message) }
}

async function onSaveNode(p: { node_id: string; content: string }) {
  try {
    await api.putNode(p.node_id, p.content)
    message.success('节点已保存')
    onSelectNode(p.node_id)
    loadNodes(nodePage.value)
  } catch (e: any) { message.error(e.message) }
}

async function onDeleteNode(id: string) {
  try {
    await api.deleteNode(id, true)
    message.success('节点已删除')
    loadNodes(nodePage.value)
    loadGraphData()
    rightView.value = 'config'
  } catch (e: any) { message.error(e.message) }
}

async function loadSettings() {
  try {
    settings.value = await api.getSettings()
  } catch { /* config not critical */ }
}

async function onSaveSettings(s: SettingsResponse) {
  try {
    await api.putSettings(s)
    savedHint.value = '配置已更新（运行时生效，未写回 .env 文件）'
    message.success('配置已更新')
  } catch (e: any) { message.error(e.message) }
}

// ── Init ──
onMounted(async () => {
  await Promise.all([
    refreshHash(),
    loadHealth(),
    loadEvents(),
    loadNodes(),
    loadGraphData(),
    loadSettings(),
  ])
})
</script>

<style>
html, body, #app { margin: 0; padding: 0; height: 100%; overflow: hidden; }
.app-layout { height: 100vh; display: flex; flex-direction: column; }
.app-content { flex: 1; display: flex; overflow: hidden; }
.center-panel { flex: 1; overflow: hidden; }
</style>
