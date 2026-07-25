<template>
  <div class="graph-tab">
    <!-- 上方：图可视化 -->
    <div class="graph-canvas-area">
      <GraphCanvas :nodes="graphNodes" :edges="graphEdges" :highlight-node-id="highlightId" @select-node="onSelectNode" @double-click-node="onDbl" />
    </div>
    <!-- 下方：节点面板（可折叠） -->
    <div :class="['panel-slider', panelOpen ? 'open' : 'closed']">
      <div class="panel-body">
        <div class="panel-inner">
          <div class="panel-left">
            <h4>新建节点</h4>
            <n-input v-model:value="newTitle" placeholder="标题" size="small" style="margin-bottom:4px" />
            <n-input v-model:value="newContent" type="textarea" placeholder="内容" size="small" :rows="2" style="margin-bottom:4px" />
            <n-select v-model:value="newEventId" :options="eventOpts" placeholder="关联事件（可选）" size="small" clearable filterable style="margin-bottom:4px" />
            <n-select v-model:value="newLinks" :options="nodeOpts" placeholder="关联节点（可选）" size="small" multiple clearable filterable style="margin-bottom:4px" />
            <n-checkbox v-model:checked="autoLink">自动关联</n-checkbox>
            <n-button size="small" type="primary" :disabled="!newTitle.trim()" @click="doCreateNode" style="margin-top:6px">创建</n-button>

            <n-divider style="margin:8px 0" />

            <h4>添加关联</h4>
            <n-select v-model:value="edgeSource" :options="nodeOpts" placeholder="源节点" size="small" filterable style="margin-bottom:4px" />
            <n-select v-model:value="edgeTarget" :options="nodeOpts" placeholder="目标节点" size="small" filterable style="margin-bottom:4px" />
            <n-input v-model:value="edgeRelation" placeholder="关系描述" size="small" style="margin-bottom:4px" />
            <n-button size="small" type="primary" :disabled="!edgeSource || !edgeTarget || !edgeRelation.trim()" @click="doCreateEdge">添加关联</n-button>

            <n-divider v-if="highlightId" style="margin:8px 0" />

            <div v-if="highlightId" class="selected-actions">
              <div class="sel-title">{{ getHighlightNodeTitle() }}</div>
              <n-input v-model:value="editNodeContent" placeholder="修改内容" size="small" style="margin-bottom:4px" />
              <n-button size="tiny" :disabled="!editNodeContent.trim()" @click="doModifyNode" style="margin-right:4px">保存修改</n-button>
              <n-button size="tiny" type="error" @click="onDeleteNode">删除节点</n-button>
              <template v-if="nodeEdges.length">
                <n-divider style="margin:6px 0" />
                <div class="edge-list-label">关联边（{{ nodeEdges.length }}）</div>
                <div v-for="e in nodeEdges" :key="e.source + e.target" class="edge-row">
                  <span class="edge-text">{{ getNodeTitle(e.source) }} → {{ getNodeTitle(e.target) }} : {{ e.relation }}</span>
                  <n-button size="tiny" quaternary circle type="error" @click="onDeleteEdge(e.source, e.target)">✕</n-button>
                </div>
              </template>
            </div>
          </div>
          <div class="panel-right">
            <h4>
              <span>节点列表</span>
              <n-button v-if="selNodeIds.size > 0" size="tiny" type="error" @click="onDeleteSelNodes" style="float:right">删除选中（{{ selNodeIds.size }}）</n-button>
            </h4>
            <div class="node-list-scroll">
              <div v-for="n in nodeItems" :key="n.node_id" class="node-mini-row" @click="onSelectNode(n.node_id)">
                <n-checkbox size="tiny" :checked="selNodeIds.has(n.node_id)" @click.stop @update:checked="toggleSelNode(n.node_id)" style="margin-right:2px" />
                <span class="nd-title">{{ n.title }}</span>
                <n-tag size="tiny" :bordered="false">{{ n.node_type }}</n-tag>
                <span class="nd-conf">{{ n.confidence.toFixed(2) }}</span>
              </div>
              <n-empty v-if="nodeItems.length === 0" description="暂无节点" size="small" style="padding:20px" />
            </div>
          </div>
        </div>
        <div class="toggle-row">
          <n-button size="tiny" type="warning" tertiary @click="onClearGraph">清空图数据</n-button>
          <n-button size="tiny" @click="panelOpen = false">收起面板 ▲</n-button>
        </div>
      </div>
    </div>
    <!-- 底部常驻切换栏 -->
    <div class="toggle-bar">
      <n-button v-if="!panelOpen" size="tiny" @click="panelOpen = true">展开面板 ▼</n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { createDiscreteApi } from 'naive-ui'
import GraphCanvas from '@/components/GraphCanvas.vue'
import * as api from '@/api/client'
import type { NodeListItem, EdgeInfo } from '@/api/client'

const { message } = createDiscreteApi(['message'])

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
const newLinks = ref<string[]>([])
const edgeSource = ref<string | null>(null)
const edgeTarget = ref<string | null>(null)
const edgeRelation = ref('')
const editNodeContent = ref('')
const selNodeIds = ref(new Set<string>())

function toggleSelNode(id: string) {
  const s = selNodeIds.value
  if (s.has(id)) s.delete(id); else s.add(id)
  selNodeIds.value = new Set(s)
}

const nodeOpts = computed(() => nodeItems.value.map(n => ({ label: n.title, value: n.node_id })))
const nodeEdges = computed(() => graphEdges.value.filter(e => e.source === highlightId.value || e.target === highlightId.value))

function getNodeTitle(id: string): string {
  const n = nodeItems.value.find(n => n.node_id === id)
  return n ? n.title : id.slice(0, 8)
}

function getHighlightNodeTitle(): string {
  const n = nodeItems.value.find(n => n.node_id === highlightId.value)
  return n ? n.title : ''
}

async function loadGraph() {
  try {
    const all = await api.listNodes({ limit: 200 })
    graphNodes.value = all.items
    nodeItems.value = all.items
    // 收集所有节点的边，去重
    const edgeMap = new Map<string, EdgeInfo>()
    for (const n of all.items) {
      try {
        const nd = await api.getNode(n.node_id)
        for (const e of nd.edges) {
          edgeMap.set(`${e.source}|${e.target}`, e)
        }
      } catch { /* skip */ }
    }
    graphEdges.value = Array.from(edgeMap.values())
    selNodeIds.value = new Set()
  } catch (e: any) {
    message.error('加载图谱失败: ' + (e.message || '未知错误'))
  }
}
async function loadEvents() {
  try {
    const res = await api.listEvents({ limit: 50 })
    eventOpts.value = res.items.map(e => ({
      label: `${(e.raw_content || '').slice(0, 28)}${(e.raw_content || '').length > 28 ? '…' : ''} (${e.event_type})`,
      value: e.event_id,
    }))
  } catch (e: any) {
    message.error('加载事件列表失败: ' + (e.message || '未知错误'))
  }
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
  try {
    const resp = await api.createNode(
      newTitle.value,
      newContent.value,
      newEventId.value || '',
    )
    const nodeId = resp.node_id

    // 创建关联边
    for (const linkId of newLinks.value) {
      await api.createEdge(nodeId, linkId, '关联', '')
    }

    newTitle.value = ''
    newContent.value = ''
    newEventId.value = null
    newLinks.value = []
    await loadGraph()
    message.success('节点已创建')
  } catch (e: any) {
    message.error('创建节点失败: ' + (e.message || '未知错误'))
  }
}

async function doCreateEdge() {
  if (!edgeSource.value || !edgeTarget.value || !edgeRelation.value.trim()) return
  try {
    await api.createEdge(edgeSource.value, edgeTarget.value, edgeRelation.value)
    edgeSource.value = null
    edgeTarget.value = null
    edgeRelation.value = ''
    await loadGraph()
    message.success('关联边已添加')
  } catch (e: any) {
    message.error('添加关联失败: ' + (e.message || '未知错误'))
  }
}

async function doModifyNode() {
  if (!highlightId.value || !editNodeContent.value.trim()) return
  try {
    await api.putNode(highlightId.value, editNodeContent.value)
    editNodeContent.value = ''
    await loadGraph()
    message.success('节点内容已更新')
  } catch (e: any) {
    message.error('修改失败: ' + (e.message || '未知错误'))
  }
}

async function doDeleteNode() {
  if (!highlightId.value) return
  try {
    await api.deleteNode(highlightId.value, true)
    highlightId.value = ''
    editNodeContent.value = ''
    await loadGraph()
    message.success('节点已删除')
  } catch (e: any) {
    message.error('删除失败: ' + (e.message || '未知错误'))
  }
}

function onDeleteNode() {
  if (window.confirm('确认删除此节点？关联边将一并移除。')) {
    doDeleteNode()
  }
}

async function doClearGraph() {
  try {
    await api.clearGraph()
    highlightId.value = ''
    editNodeContent.value = ''
    await loadGraph()
    message.success('图数据已清空')
  } catch (e: any) {
    message.error('清空失败: ' + (e.message || '未知错误'))
  }
}

function onClearGraph() {
  if (window.confirm('确认清空所有节点和边？此操作不可撤销。')) {
    doClearGraph()
  }
}

async function doDeleteEdge(source: string, target: string) {
  try {
    await api.deleteEdge(source, target)
    await loadGraph()
    message.success('关联边已删除')
  } catch (e: any) {
    message.error('删除关联边失败: ' + (e.message || '未知错误'))
  }
}

function onDeleteEdge(source: string, target: string) {
  if (window.confirm(`确认删除此关联边？`)) {
    doDeleteEdge(source, target)
  }
}

async function onDeleteSelNodes() {
  const ids = Array.from(selNodeIds.value)
  if (ids.length === 0) return
  if (!window.confirm(`确认删除选中的 ${ids.length} 个节点？关联边将一并移除。`)) return
  let fail = 0
  for (const nid of ids) {
    try {
      await api.deleteNode(nid, true)
    } catch { fail++ }
  }
  selNodeIds.value = new Set()
  if (fail === 0) {
    message.success(`${ids.length} 个节点已删除`)
  } else {
    message.warning(`删除完成：${ids.length - fail} 成功，${fail} 失败`)
  }
  highlightId.value = ''
  editNodeContent.value = ''
  await loadGraph()
}
</script>

<style scoped>
.graph-tab { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; position: relative; }
.graph-canvas-area { flex: 1; min-height: 0; position: relative; z-index: 1; }
.panel-slider { position: absolute; left: 0; right: 0; bottom: 0; z-index: 2; transition: transform 0.25s ease; }
.panel-slider.open { transform: translateY(0); }
.panel-slider.closed { transform: translateY(100%); }
.panel-body { height: 40vh; display: flex; flex-direction: column; background: var(--n-color); border-top: 1px solid var(--n-border-color); overflow: hidden; }
.panel-inner { display: flex; flex: 1; min-height: 0; overflow-y: auto; }
.panel-left, .panel-right { flex: 1; padding: 8px; overflow-y: auto; }
.panel-left { border-right: 1px solid var(--n-border-color); }
.node-list-scroll { flex: 1; min-height: 0; overflow-y: auto; }
.node-mini-row {
  display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 3px 4px; cursor: pointer; border-radius: 3px;
}
.node-mini-row:hover { background: rgba(255,255,255,0.05); }
.nd-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nd-conf { color: var(--n-text-color-3); width: 36px; text-align: right; }
.toggle-row { flex-shrink: 0; display: flex; justify-content: space-between; align-items: center; padding: 3px 8px; border-top: 1px solid var(--n-border-color); background: var(--n-color); }
.toggle-bar { display: flex; align-items: center; justify-content: flex-end; padding: 2px 8px; background: var(--n-color); border-top: 1px solid var(--n-border-color); flex-shrink: 0; min-height: 28px; }
h4 { margin: 0 0 6px; font-size: 13px; }
.sel-title { font-size: 13px; font-weight: 600; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.edge-list-label { font-size: 12px; color: var(--n-text-color-3); margin-bottom: 3px; }
.edge-row { display: flex; align-items: center; gap: 4px; font-size: 11px; padding: 2px 0; }
.edge-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
