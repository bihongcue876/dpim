<template>
  <div class="graph-tab">
    <!-- 上方：图可视化 -->
    <div class="graph-canvas-area" :class="{ collapsed: !panelOpen }">
      <GraphCanvas :key="panelOpen ? 'open' : 'closed'" :nodes="graphNodes" :edges="graphEdges" :highlight-node-id="highlightId" @select-node="onSelectNode" @double-click-node="onDbl" />
    </div>
    <!-- 下方：节点面板（可折叠） -->
    <div v-if="panelOpen" class="node-panel">
      <div class="panel-left">
        <h4>新建节点</h4>
        <n-input v-model:value="newTitle" placeholder="标题" size="small" style="margin-bottom:4px" />
        <n-input v-model:value="newContent" type="textarea" placeholder="内容" size="small" :rows="2" style="margin-bottom:4px" />
        <n-select v-model:value="newEventId" :options="eventOpts" placeholder="关联事件（可选）" size="small" clearable filterable style="margin-bottom:4px" />
        <n-checkbox v-model:checked="autoLink">自动关联</n-checkbox>
        <n-button size="small" type="primary" :disabled="!newTitle.trim()" @click="doCreateNode" style="margin-top:6px">创建</n-button>
      </div>
      <div class="panel-right">
        <h4>节点列表</h4>
        <div class="node-list-scroll">
          <div v-for="n in nodeItems" :key="n.node_id" class="node-mini-row" @click="onSelectNode(n.node_id)">
            <span class="nd-title">{{ n.title }}</span>
            <n-tag size="tiny" :bordered="false">{{ n.node_type }}</n-tag>
            <span class="nd-conf">{{ n.confidence.toFixed(2) }}</span>
          </div>
          <n-empty v-if="nodeItems.length === 0" description="暂无节点" size="small" style="padding:20px" />
        </div>
      </div>
    </div>
    <!-- 折叠按钮 -->
    <n-button size="tiny" class="toggle-btn" @click="panelOpen = !panelOpen">
      {{ panelOpen ? '收起面板 ▲' : '展开面板 ▼' }}
    </n-button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import GraphCanvas from '@/components/GraphCanvas.vue'
import * as api from '@/api/client'
import type { NodeListItem, EdgeInfo, NodeDetail } from '@/api/client'

const props = defineProps<{ keyStatus: string }>()

const panelOpen = ref(true)
const highlightId = ref('')
const graphNodes = ref<NodeListItem[]>([])
const graphEdges = ref<EdgeInfo[]>([])
const nodeItems = ref<NodeListItem[]>([])
const newTitle = ref('')
const newContent = ref('')
const newEventId = ref<string | null>(null)
const autoLink = ref(false)
const eventOpts = ref<Array<{ label: string; value: string }>>([])

async function loadGraph() {
  try {
    const all = await api.listNodes({ limit: 200 })
    graphNodes.value = all.items
    nodeItems.value = all.items
    if (all.items.length > 0) {
      const nd = await api.getNode(all.items[0].node_id)
      graphEdges.value = nd.edges
    }
  } catch { /* ignore */ }
}
async function loadEvents() {
  try {
    const res = await api.listEvents({ limit: 50 })
    eventOpts.value = res.items.map(e => ({ label: `${e.event_id.slice(0,12)}… (${e.event_type})`, value: e.event_id }))
  } catch { /* ignore */ }
}

watch(() => props.keyStatus, async () => { await loadGraph(); await loadEvents() }, { immediate: true })

function onSelectNode(id: string) {
  highlightId.value = id
}
function onDbl(id: string) {
  // Future: open detail modal
}

async function doCreateNode() {
  if (!newTitle.value.trim()) return
  const content = newEventId.value
    ? `[node] ${newTitle.value}\n${newContent.value}\n来源: ${newEventId.value}`
    : `[node] ${newTitle.value}\n${newContent.value}`
  try {
    await api.ingest(content, 'data')
    newTitle.value = ''
    newContent.value = ''
    newEventId.value = null
    await loadGraph()
  } catch { /* ignore */ }
}
</script>

<style scoped>
.graph-tab { height: 100%; position: relative; display: flex; flex-direction: column; }
.graph-canvas-area { flex: 1; min-height: 0; }
.graph-canvas-area.collapsed { flex: 1; }
.node-panel { display: flex; border-top: 1px solid var(--n-border-color); flex: 0 0 35%; overflow: hidden; }
.panel-left, .panel-right { flex: 1; padding: 8px; overflow-y: auto; }
.panel-left { border-right: 1px solid var(--n-border-color); }
.node-list-scroll { overflow-y: auto; height: calc(100% - 24px); }
.node-mini-row {
  display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 3px 4px; cursor: pointer; border-radius: 3px;
}
.node-mini-row:hover { background: rgba(255,255,255,0.05); }
.nd-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nd-conf { color: var(--n-text-color-3); width: 36px; text-align: right; }
.toggle-btn { position: absolute; bottom: 4px; right: 8px; z-index: 10; }
h4 { margin: 0 0 6px; font-size: 13px; }
</style>
