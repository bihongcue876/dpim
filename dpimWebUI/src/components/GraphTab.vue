<template>
  <div class="graph-tab">
    <!-- 图可视化：始终 100% 占满，面板只是覆盖/露出 -->
    <div class="graph-canvas-area">
      <GraphCanvas :nodes="graphNodes" :edges="graphEdges" :highlight-node-id="highlightId"
        :refresh-epoch="refreshEpoch"
        @select-node="onSelectNode" @double-click-node="onDbl"
        @select-edge="onSelectEdge" />
      <div class="canvas-toolbar">
        <n-button size="tiny" quaternary circle @click="refreshGraph" title="重新布局">↻</n-button>
      </div>
    </div>
    <!-- 面板：向下滑出画布（translateY），canvas 尺寸不变 -->
    <div :class="['panel-slider', panelOpen ? 'open' : 'closed']">
      <div class="panel-body">
        <div class="panel-inner">
          <div class="panel-left">
            <h4>新建节点</h4>
            <n-input v-model:value="newTitle" placeholder="标题" size="small" style="margin-bottom:4px" />
            <n-input v-model:value="newContent" type="textarea" placeholder="内容" size="small" :rows="2" style="margin-bottom:4px" />
            <n-select v-model:value="newEventId" :options="eventOpts" placeholder="关联事件（可选）" size="small" clearable filterable style="margin-bottom:4px" />
            <n-button size="small" type="primary" :disabled="!newTitle.trim()" :loading="creatingNode" @click="doCreateNode" style="margin-top:6px">创建</n-button>

            <n-divider style="margin:8px 0" />

            <h4>添加关联</h4>
            <n-select v-model:value="edgeSource" :options="nodeOpts" placeholder="源节点" size="small" filterable style="margin-bottom:4px" />
            <n-select v-model:value="edgeTarget" :options="nodeOpts" placeholder="目标节点" size="small" filterable style="margin-bottom:4px" />
            <n-input v-model:value="edgeRelation" placeholder="关系描述" size="small" style="margin-bottom:4px" />
            <n-button size="small" type="primary" :disabled="!edgeSource || !edgeTarget || !edgeRelation.trim()" :loading="creatingEdge" @click="doCreateEdge">添加关联</n-button>

            <!-- 选中边的详情和编辑 -->
            <n-divider v-if="selectedEdge" style="margin:8px 0" />
            <div v-if="selectedEdge" class="selected-actions">
              <div class="sel-title">关联边</div>
              <div class="edge-detail-row">{{ getNodeTitle(selectedEdge.source) }} → {{ getNodeTitle(selectedEdge.target) }}</div>
              <n-input v-model:value="selectedEdgeRelation" placeholder="修改关系描述" size="small" style="margin-bottom:4px" />
              <n-button size="tiny" :disabled="!selectedEdgeRelation.trim()" @click="doModifyEdgeRelation" style="margin-right:4px">保存关系</n-button>
              <n-button size="tiny" type="error" @click="onDeleteSelectedEdge">删除此边</n-button>
            </div>

            <n-divider v-if="highlightId" style="margin:8px 0" />

            <div v-if="nodeDetail" class="selected-actions">
              <div class="sel-title">{{ nodeDetail.title }}</div>
              <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
                <n-tag size="tiny" :bordered="false" :type="nodeTypeTag(nodeDetail.node_type)">{{ nodeDetail.node_type }}</n-tag>
                <span style="font-size:11px;color:var(--n-text-color-3)">置信度 {{ nodeDetail.confidence.toFixed(2) }}</span>
              </div>

              <n-descriptions size="small" :column="1" label-placement="left">
                <n-descriptions-item label="节点 ID">
                  <span class="mono-text">{{ nodeDetail.node_id.slice(0, 20) }}…</span>
                </n-descriptions-item>
                <n-descriptions-item label="内容">
                  <template v-if="editing">
                    <n-input v-model:value="editNodeContent" type="textarea" :rows="4" />
                  </template>
                  <div v-else class="node-content">{{ nodeDetail.content }}</div>
                </n-descriptions-item>
              </n-descriptions>

              <div class="detail-actions" style="margin-top:8px">
                <template v-if="editing">
                  <n-button size="tiny" @click="cancelNodeEdit">取消</n-button>
                  <n-button size="tiny" type="primary" @click="doModifyNode" :loading="savingNode">保存</n-button>
                </template>
                <template v-else>
                  <n-button size="tiny" @click="startNodeEdit">编辑</n-button>
                  <n-button size="tiny" type="error" @click="onDeleteNode">删除节点</n-button>
                </template>
              </div>

              <template v-if="nodeDetail.source_refs && nodeDetail.source_refs.length > 0">
                <n-divider style="margin:6px 0" />
                <div class="detail-label">源事件（{{ nodeDetail.source_refs.length }}）</div>
                <div v-for="sr in nodeDetail.source_refs" :key="sr.event_id" class="source-ref-row">
                  <span class="mono-text">{{ sr.event_id.slice(0, 16) }}…</span>
                  <n-tag size="tiny" :bordered="false" :type="sr.valid ? 'success' : 'error'">{{ sr.valid ? '有效' : '无效' }}</n-tag>
                </div>
              </template>

              <template v-if="nodeDetail.edges && nodeDetail.edges.length > 0">
                <n-divider style="margin:6px 0" />
                <div class="detail-label">关联边（{{ nodeDetail.edges.length }}）</div>
                <div v-for="e in nodeDetail.edges" :key="e.source + e.target" class="edge-row">
                  <span class="edge-text">{{ getNodeTitle(e.source) }} → {{ getNodeTitle(e.target) }} : {{ e.relation }}</span>
                  <n-button size="tiny" quaternary circle type="error" @click="onDeleteEdge(e.source, e.target)">✕</n-button>
                </div>
              </template>
            </div>
            <n-spin v-else-if="loadingNodeDetail" size="small" style="padding:20px" />
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
      </div>
    </div>
    <!-- 底部操作栏：常驻页面底部 -->
    <div class="toggle-row">
      <n-button size="tiny" type="warning" tertiary @click="onClearGraph">清空图数据</n-button>
      <n-button v-if="panelOpen" size="tiny" @click="collapsePanel">收起面板 ▼</n-button>
      <n-button v-else size="tiny" @click="expandPanel">展开面板 ▲</n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { createDiscreteApi } from 'naive-ui'
import GraphCanvas from '@/components/GraphCanvas.vue'
import * as api from '@/api/client'
import type { NodeListItem, EdgeInfo, NodeDetail } from '@/api/client'

const { message, dialog } = createDiscreteApi(['message', 'dialog'])

const props = defineProps<{ keyStatus: string }>()

const panelOpen = ref(true)
const refreshEpoch = ref(0)
const highlightId = ref('')
const graphNodes = ref<NodeListItem[]>([])
const graphEdges = ref<EdgeInfo[]>([])
const nodeItems = ref<NodeListItem[]>([])
const newTitle = ref('')
const newContent = ref('')
const newEventId = ref<string | null>(null)
const eventOpts = ref<Array<{ label: string; value: string }>>([])
const edgeSource = ref<string | null>(null)
const edgeTarget = ref<string | null>(null)
const edgeRelation = ref('')
const editNodeContent = ref('')
const selNodeIds = ref(new Set<string>())
const creatingNode = ref(false)
const creatingEdge = ref(false)
const selectedEdge = ref<{ source: string; target: string; relation: string } | null>(null)
const selectedEdgeRelation = ref('')
const savingEdgeRelation = ref(false)
const nodeDetail = ref<NodeDetail | null>(null)
const loadingNodeDetail = ref(false)
const editing = ref(false)
const savingNode = ref(false)

function nodeTypeTag(t: string) {
  if (t === 'system') return 'info'
  if (t === 'interaction') return 'success'
  if (t === 'data') return 'warning'
  return 'default'
}

function expandPanel() {
  panelOpen.value = true
  refreshEpoch.value++
}
function collapsePanel() {
  panelOpen.value = false
  refreshEpoch.value++
}

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

async function refreshGraph() {
  await loadGraph()
  refreshEpoch.value++
}

async function loadGraph() {
  try {
    const all = await api.listNodes({ limit: 400 })
    graphNodes.value = all.items
    nodeItems.value = all.items
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

// 跨 Tab 定位：监听来自检索 Tab 的焦点节点事件（不依赖 keyStatus 变化）
function applyFocusNode() {
  const focusId = localStorage.getItem('dpim_focus_node')
  if (focusId && nodeItems.value.some(n => n.node_id === focusId)) {
    highlightId.value = focusId
    localStorage.removeItem('dpim_focus_node')
    onSelectNode(focusId)
  }
}
const onFocusNode = (() => { applyFocusNode() }) as EventListener

onMounted(() => {
  window.addEventListener('dpim:focus-node', onFocusNode)
})
onUnmounted(() => {
  window.removeEventListener('dpim:focus-node', onFocusNode)
})

function onSelectNode(id: string) {
  highlightId.value = id
  selectedEdge.value = null
  editNodeContent.value = ''
  nodeDetail.value = null
  loadingNodeDetail.value = true
  editing.value = false
  api.getNode(id).then(d => {
    nodeDetail.value = d
    editNodeContent.value = d.content
  }).catch(() => {
    message.error('加载节点详情失败')
  }).finally(() => {
    loadingNodeDetail.value = false
  })
}
function onDbl(id: string) {
  // Future: open detail modal
}

function onSelectEdge(source: string, target: string, relation: string) {
  highlightId.value = ''  // 清除节点选中
  selectedEdge.value = { source, target, relation }
  selectedEdgeRelation.value = relation
}

async function doModifyEdgeRelation() {
  if (!selectedEdge.value || !selectedEdgeRelation.value.trim()) return
  savingEdgeRelation.value = true
  try {
    // 删除旧边，创建新边（后端无 PUT 接口）
    await api.deleteEdge(selectedEdge.value.source, selectedEdge.value.target)
    await api.createEdge(selectedEdge.value.source, selectedEdge.value.target, selectedEdgeRelation.value)
    selectedEdge.value.relation = selectedEdgeRelation.value
    message.success('关联关系已更新')
    await loadGraph()
  } catch (e: any) {
    message.error('更新失败: ' + (e.message || '未知错误'))
  } finally { savingEdgeRelation.value = false }
}

function onDeleteSelectedEdge() {
  if (!selectedEdge.value) return
  dialog.warning({
    title: '确认删除关联边',
    content: `确认删除此关联边？（${getNodeTitle(selectedEdge.value.source)} → ${getNodeTitle(selectedEdge.value.target)}）`,
    positiveText: '确认删除', negativeText: '取消',
    async onPositiveClick() {
      try {
        await api.deleteEdge(selectedEdge.value!.source, selectedEdge.value!.target)
        selectedEdge.value = null
        message.success('关联边已删除')
        await loadGraph()
      } catch (e: any) { message.error('删除失败: ' + (e.message || '未知错误')) }
    },
  })
}

async function doCreateNode() {
  if (!newTitle.value.trim()) return
  creatingNode.value = true
  try {
    const resp = await api.createNode(newTitle.value, newContent.value, newEventId.value || '')
    newTitle.value = ''; newContent.value = ''; newEventId.value = null
    await loadGraph()
    message.success('节点已创建')
  } catch (e: any) {
    message.error('创建节点失败: ' + (e.message || '未知错误'))
  } finally { creatingNode.value = false }
}

async function doCreateEdge() {
  if (!edgeSource.value || !edgeTarget.value || !edgeRelation.value.trim()) return
  creatingEdge.value = true
  try {
    await api.createEdge(edgeSource.value, edgeTarget.value, edgeRelation.value)
    edgeSource.value = null; edgeTarget.value = null; edgeRelation.value = ''
    await loadGraph()
    message.success('关联边已添加')
  } catch (e: any) {
    message.error('添加关联失败: ' + (e.message || '未知错误'))
  } finally { creatingEdge.value = false }
}

async function doModifyNode() {
  if (!highlightId.value || !editNodeContent.value.trim()) return
  savingNode.value = true
  try {
    await api.putNode(highlightId.value, editNodeContent.value)
    editing.value = false
    message.success('节点内容已更新')
    // 刷新详情
    const d = await api.getNode(highlightId.value)
    nodeDetail.value = d
    editNodeContent.value = d.content
  } catch (e: any) { message.error('修改失败: ' + (e.message || '未知错误')) }
  finally { savingNode.value = false }
}

function startNodeEdit() {
  editing.value = true
}
function cancelNodeEdit() {
  editing.value = false
  if (nodeDetail.value) editNodeContent.value = nodeDetail.value.content
}

async function doDeleteNode() {
  if (!highlightId.value) return
  try {
    await api.deleteNode(highlightId.value, true)
    highlightId.value = ''; editNodeContent.value = ''
    await loadGraph()
    message.success('节点已删除')
  } catch (e: any) { message.error('删除失败: ' + (e.message || '未知错误')) }
}

function onDeleteNode() {
  dialog.warning({
    title: '确认删除', content: '确认删除此节点？关联边将一并移除。',
    positiveText: '确认删除', negativeText: '取消',
    onPositiveClick: doDeleteNode,
  })
}

async function doClearGraph() {
  try {
    await api.clearGraph()
    highlightId.value = ''; editNodeContent.value = ''
    await loadGraph()
    message.success('图数据已清空')
  } catch (e: any) { message.error('清空失败: ' + (e.message || '未知错误')) }
}

function onClearGraph() {
  dialog.warning({
    title: '确认清空', content: '确认清空所有节点和边？此操作不可撤销。',
    positiveText: '确认清空', negativeText: '取消',
    onPositiveClick: doClearGraph,
  })
}

async function doDeleteEdge(source: string, target: string) {
  try {
    await api.deleteEdge(source, target)
    await loadGraph()
    message.success('关联边已删除')
  } catch (e: any) { message.error('删除关联边失败: ' + (e.message || '未知错误')) }
}

function onDeleteEdge(source: string, target: string) {
  dialog.warning({
    title: '确认删除关联边',
    content: `确认删除此关联边？（${getNodeTitle(source)} → ${getNodeTitle(target)}）`,
    positiveText: '确认删除', negativeText: '取消',
    onPositiveClick: () => doDeleteEdge(source, target),
  })
}

async function onDeleteSelNodes() {
  const ids = Array.from(selNodeIds.value)
  if (ids.length === 0) return
  dialog.warning({
    title: '批量删除节点',
    content: `确认删除选中的 ${ids.length} 个节点？关联边将一并移除。`,
    positiveText: '确认删除', negativeText: '取消',
    async onPositiveClick() {
      let fail = 0
      for (const nid of ids) { try { await api.deleteNode(nid, true) } catch { fail++ } }
      selNodeIds.value = new Set()
      if (fail === 0) message.success(`${ids.length} 个节点已删除`)
      else message.warning(`删除完成：${ids.length - fail} 成功，${fail} 失败`)
      highlightId.value = ''; editNodeContent.value = ''
      await loadGraph()
    },
  })
}
</script>

<style scoped>
.graph-tab { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; position: relative; }
.graph-canvas-area { flex: 1; width: 100%; min-height: 0; position: relative; background: var(--dpim-bg, #0e1217); }
.canvas-toolbar { position: absolute; top: 8px; right: 8px; z-index: 5; display: flex; gap: 4px; }

/* 面板：absolute 定位 + translateY 向下滑出画布，canvas 始终 100% */
.panel-slider {
  position: absolute; left: 0; right: 0; bottom: 32px; height: 40vh; z-index: 2;
  transition: transform 0.25s ease;
}
.panel-slider.open { transform: translateY(0); }
.panel-slider.closed { transform: translateY(calc(100% + 32px)); }

.panel-body {
  height: 100%; display: flex; flex-direction: column;
  background: var(--dpim-surface, #161b22);
  border-top: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  overflow: hidden;
}
.panel-inner { display: flex; flex: 1; min-height: 0; overflow-y: auto; }
.panel-left, .panel-right { flex: 1; padding: 12px 16px; overflow-y: auto; }
.panel-left { border-right: 1px solid var(--dpim-border, rgba(255,255,255,0.09)); }
.node-list-scroll { flex: 1; min-height: 0; overflow-y: auto; }
.node-mini-row {
  display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 6px 8px;
  cursor: pointer; border-radius: 6px; border-left: 2px solid transparent;
}
.node-mini-row:hover { background: var(--dpim-surface-hover, rgba(255,255,255,0.04)); }
.nd-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--dpim-text-2, #aab4c0); }
.nd-conf { color: var(--dpim-text-3, #7c8694); width: 40px; text-align: right; font-size: 12px; font-family: 'Cascadia Code', Consolas, monospace; }

/* 底部操作栏：absolute 定在页面最底部 */
.toggle-row {
  position: absolute; left: 0; right: 0; bottom: 0; height: 32px; z-index: 3;
  display: flex; justify-content: space-between; align-items: center;
  padding: 3px 12px; background: var(--dpim-surface, #161b22);
  border-top: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
}
h4 { margin: 0 0 10px; font-size: 14px; color: var(--dpim-text, #e6edf3); }
.sel-title { font-size: 14px; font-weight: 600; margin-bottom: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--dpim-text, #e6edf3); }
.edge-list-label { font-size: 13px; color: var(--dpim-text-3, #7c8694); margin-bottom: 4px; }
.edge-row { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 4px 0; }
.edge-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--dpim-text-2, #aab4c0); }
.node-content {
  font-size: 13px; line-height: 1.6; white-space: pre-wrap; max-height: 200px; overflow-y: auto;
  background: var(--dpim-bg, #0e1217); border: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  padding: 10px 12px; border-radius: var(--dpim-radius-sm, 8px);
  color: var(--dpim-text-2, #aab4c0);
}
.detail-label { font-size: 13px; font-weight: 600; color: var(--dpim-text-3, #7c8694); margin-bottom: 4px; }
.source-ref-row { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 4px 0; }
.mono-text { font-family: 'Cascadia Code', Consolas, monospace; font-size: 12px; color: var(--dpim-text-3, #7c8694); }
</style>
