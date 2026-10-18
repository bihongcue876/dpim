<template>
  <PageShell
    zone="查阅"
    title="信息图谱"
    description="看衍生知识的关联结构（节点 = 衍生知识，可由 AI 维护）"
  >
    <!-- 唯一主操作（P4）：刷新 = 重取数据 + 重新布局 -->
    <template #actions>
      <n-button type="primary" size="small" :loading="loading" @click="refreshGraph">刷新</n-button>
    </template>

    <Toolbar>
      <n-select
        v-model:value="typeFilter"
        size="small"
        class="f-select"
        :options="TYPE_OPTIONS"
        placeholder="节点类型"
        clearable
      />
      <n-button size="small" quaternary @click="relayout">重新布局</n-button>
      <span class="tool-meta">
        节点 {{ filteredNodes.length }} / {{ allNodes.length }} · 关联 {{ filteredEdges.length }}
        <template v-if="nodesTruncated">
          （节点已截断：已取前 {{ allNodes.length }} / 共 {{ nodesTotal }}{{ scope.isJoint.value ? '；联查态每个书目最多只取 100 个候选，故「共」也只是候选池的数、可能不是全部' : '' }}）
        </template>
        <template v-else-if="scope.isJoint.value">
          （联查态每个书目最多只取 100 个候选节点，可能不是全部）
        </template>
        <template v-if="edgesSkipped">
          （另有 {{ edgesSkipped }} 条边的端点不在已加载节点里，未绘制）
        </template>
        <template v-if="edgesTruncated">
          （边已截断：已取前 {{ edgesReceived }} / 共 {{ edgesTotal }}）
        </template>
      </span>
      <template #right>
        <span class="scope-note">{{ scope.scopeLabel.value }}</span>
        <n-button size="small" @click="openCreateNode">新建节点</n-button>
        <n-button size="small" @click="openCreateEdge">建边</n-button>
        <n-button size="small" type="error" ghost @click="clearOpen = true">清空图层</n-button>
      </template>
    </Toolbar>

    <!-- P6 失败可见：错误原文常驻页面（不只在 toast 里闪一下） -->
    <div v-if="visibleError" class="error-strip">
      <span class="error-text">{{ visibleError }}</span>
      <n-button size="tiny" quaternary @click="dismissError">关闭</n-button>
      <n-button size="tiny" @click="retryAfterError">重试</n-button>
    </div>

    <div class="split">
      <!-- 画布：拖拽 / 缩放 / 点选节点（三态互斥，有节点时不显示空态） -->
      <div class="canvas-card">
        <GraphCanvas
          v-if="filteredNodes.length"
          :nodes="filteredNodes"
          :edges="filteredEdges"
          :highlight-node-id="selectedId || null"
          :refresh-epoch="refreshEpoch"
          @select-node="onCanvasSelect"
          @double-click-node="onCanvasSelect"
          @select-edge="onSelectEdge"
        />
        <StateBlock
          v-else
          :loading="loading"
          :error="allNodes.length ? '' : error"
          :empty-text="allNodes.length ? '当前筛选没有匹配的节点' : '这个书目还没有衍生知识'"
          :hint="emptyHint"
        >
          <template #retry>
            <n-button size="small" @click="refreshGraph">重试</n-button>
          </template>
        </StateBlock>

        <!-- 图例：节点类型配色 + 边方向（纯展示，配色与 GraphCanvas 读取的令牌一致） -->
        <div v-if="filteredNodes.length" class="legend" aria-hidden="true">
          <span class="legend-item"><i class="legend-dot legend-dot--system" />系统 system</span>
          <span class="legend-item"><i class="legend-dot legend-dot--interaction" />交互 interaction</span>
          <span class="legend-item"><i class="legend-dot legend-dot--data" />数据 data</span>
          <span class="legend-item legend-item--dim">圆点大小 = 置信度</span>
          <span class="legend-item legend-item--dim">边方向：源节点 → 目标节点</span>
        </div>

        <!-- 选中的边：就地显示并可删除 -->
        <div v-if="selectedEdge" class="edge-chip">
          <span class="edge-chip-text">
            {{ nodeTitle(selectedEdge.source) }} → {{ nodeTitle(selectedEdge.target) }}：{{ selectedEdge.relation }}
          </span>
          <n-button size="tiny" quaternary type="error" @click="askDeleteEdge(selectedEdge)">删除边</n-button>
        </div>
      </div>

      <!-- 节点详情（右侧）：内容修订 + 源证管理 + 关联边 + 删除 -->
      <div class="detail-wrap">
        <DetailPanel
          :title="detail ? detail.title : '未选择节点'"
          :subtitle="detail ? detail.node_id : '在左侧画布点选一个节点'"
        >
          <template #head-actions>
            <OriginBadge kind="derived" />
          </template>

          <template v-if="detail" #meta>
            <span>类型：{{ typeText(detail.node_type) }}</span>
            <span>置信度：{{ detail.confidence.toFixed(2) }}</span>
            <span>源证：{{ validRefCount }} / {{ sourceRefs.length }} 有效</span>
            <span v-if="scope.isJoint.value">来自书目：《{{ write.nameOf(selectedRepoId) }}》</span>
          </template>

          <StateBlock
            v-if="!selectedId"
            empty-text="未选择节点"
            hint="在左侧画布点选一个节点，即可查看内容、源证与关联边。"
            fixed-height
          />
          <StateBlock v-else-if="detailLoading" loading fixed-height />
          <StateBlock v-else-if="detailError" :error="detailError" fixed-height>
            <template #retry>
              <n-button size="small" @click="reloadDetail">重试</n-button>
            </template>
          </StateBlock>

          <template v-else-if="detail">
            <section class="block">
              <div class="block-head">
                <h4 class="block-title">内容</h4>
                <n-button v-if="!editing && !isSystemNode" size="tiny" quaternary @click="startEdit">
                  修订
                </n-button>
              </div>
              <p v-if="isSystemNode" class="note">
                system 节点由人工登记，图层不提供内容修订入口。
              </p>
              <template v-if="editing">
                <n-input
                  v-model:value="draftContent"
                  type="textarea"
                  :autosize="{ minRows: 5, maxRows: 16 }"
                  placeholder="节点内容（一节点一要点）"
                />
                <div class="row-actions">
                  <n-button size="small" type="primary" :loading="saving" @click="saveContent">
                    保存
                  </n-button>
                  <n-button size="small" quaternary @click="editing = false">取消</n-button>
                </div>
              </template>
              <pre v-else class="content">{{ detail.content }}</pre>
            </section>

            <section class="block">
              <div class="block-head">
                <h4 class="block-title">源事件（源证）</h4>
                <span class="note">后端守卫：最少保留 1 条有效源证，移除最后一条会被拒绝（409）</span>
              </div>
              <div v-if="sourceRefs.length" class="ref-list">
                <div v-for="ref in sourceRefs" :key="ref.event_id" class="ref-row">
                  <span class="mono">{{ ref.event_id }}</span>
                  <span class="ref-state" :class="ref.valid ? 'ref-state--ok' : 'ref-state--bad'">
                    {{ ref.valid ? '有效' : '无效' }}
                  </span>
                  <n-button
                    size="tiny"
                    quaternary
                    :disabled="!ref.valid"
                    @click="jumpEvent(ref.event_id)"
                  >
                    查看源事件
                  </n-button>
                  <n-button
                    size="tiny"
                    quaternary
                    type="error"
                    :disabled="!canRemoveRef(ref)"
                    :title="canRemoveRef(ref) ? '移除该源证' : '最少保留 1 条有效源证'"
                    :loading="removingRefId === ref.event_id"
                    @click="removeRef(ref.event_id)"
                  >
                    移除
                  </n-button>
                </div>
              </div>
              <p v-else class="note">该节点没有任何源证（正常构图不会出现这种情况）。</p>
              <div class="ref-add">
                <n-input
                  v-model:value="newRefId"
                  size="small"
                  placeholder="关联事件：粘贴事件 ID"
                  @keyup.enter="addRef"
                />
                <n-button
                  size="small"
                  :disabled="!newRefId.trim()"
                  :loading="addingRef"
                  @click="addRef"
                >
                  关联事件
                </n-button>
              </div>
            </section>

            <section class="block">
              <div class="block-head">
                <h4 class="block-title">关联边（{{ nodeEdges.length }}）</h4>
              </div>
              <div v-if="nodeEdges.length" class="edge-list">
                <div
                  v-for="edge in nodeEdges"
                  :key="`${edge.source}|${edge.target}|${edge.relation}`"
                  class="edge-row"
                >
                  <span class="edge-text">
                    {{ nodeTitle(edge.source) }} → {{ nodeTitle(edge.target) }}：{{ edge.relation }}
                  </span>
                  <n-button size="tiny" quaternary type="error" @click="askDeleteEdge(edge)">
                    删除
                  </n-button>
                </div>
              </div>
              <p v-else class="note">该节点没有关联边。</p>
            </section>
          </template>

          <template v-if="detail" #actions>
            <n-button size="small" type="error" ghost @click="askDeleteNode">删除节点</n-button>
          </template>
        </DetailPanel>
      </div>
    </div>

    <!-- 删除节点：先按非强制删除；后端因有效源证返回 409 → 说明影响后带 force 重试 -->
    <ConfirmDialog
      v-model:show="deleteOpen"
      danger
      title="删除这个知识节点？"
      :message="detail ? detail.title : ''"
      :impacts="[
        '该节点的关联边会一并移除；节点内容为衍生知识（可由原文重新派生）。',
        '若节点仍有有效源证，后端会拒绝并要求显式强制（说明有原文在支撑它）。',
      ]"
      confirm-text="删除"
      :loading="deleting"
      @confirm="deleteNode(false)"
    />

    <ConfirmDialog
      v-model:show="forceOpen"
      danger
      title="该节点仍有有效源证"
      :message="forceMessage"
      :impacts="[
        '后端守卫：节点必须最少保留 1 条有效源证，因此普通删除被拒绝。',
        '强制删除会连同该节点的全部关联边一起移除，且不可逆。',
        '原文（时序事件存储）不受影响；如需重建该知识，需重新跑管线从原文派生。',
      ]"
      confirm-text="强制删除"
      :loading="deleting"
      @confirm="deleteNode(true)"
    />

    <!-- 清空图层：危险操作，必须二次确认并说明影响 -->
    <ConfirmDialog
      v-model:show="clearOpen"
      danger
      title="清空图层？"
      :message="`将删除活动书目《${write.activeRepoName.value}》的全部衍生知识（节点与边）`"
      :impacts="[
        '清空前会自动留档整图：可在「回收站」恢复（合并式补回，不覆盖现有图层）。',
        '原文（时序事件存储）不受影响；相关事件会从「已入图」回到「待处理」，AI 可用时补偿会重新入图。',
        `清空只作用于活动书目《${write.activeRepoName.value}》，联查勾选的其它书目不受影响。`,
      ]"
      confirm-text="清空图层"
      :loading="clearing"
      @confirm="doClearGraph"
    />

    <!-- 删除单条边 -->
    <ConfirmDialog
      v-model:show="edgeDeleteOpen"
      danger
      title="删除这条边？"
      :message="edgeDeleteText"
      :impacts="['只移除节点之间的关系，节点本身与其源证保留。', '删掉的边可由图维护重新补出。']"
      confirm-text="删除边"
      :loading="deletingEdge"
      @confirm="doDeleteEdge"
    />

    <!-- 跨书目写入守卫：写操作只作用于活动书目（不静默切换） -->
    <ConfirmDialog
      v-model:show="activateOpen"
      title="需要切换活动书目"
      message="写操作只作用于活动书目"
      :impacts="activateImpacts"
      confirm-text="切换并继续"
      :loading="activating"
      @confirm="confirmActivate"
    />

    <!-- 新建节点（衍生知识，可人工补） -->
    <n-modal :show="createNodeOpen" @update:show="(v: boolean) => (createNodeOpen = v)">
      <div class="modal-box">
        <h3 class="modal-title">新建节点（衍生知识）</h3>
        <p class="note">写入书目：{{ writeTargetName }}</p>
        <p v-if="scope.isJoint.value" class="warn-note">
          当前勾选了 {{ scope.selectedIds.value.length }} 本书目（联查 · 只读聚合）：`POST /nodes`
          不接受库参数，新建节点只写进活动书目《{{ write.activeRepoName.value }}》，不会写进联查的其它库。
        </p>
        <n-input
          v-model:value="createTitle"
          size="small"
          placeholder="标题（即要点，≤60 字符）"
        />
        <n-input
          v-model:value="createContent"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 10 }"
          placeholder="内容"
        />
        <n-input
          v-model:value="createSourceEvent"
          size="small"
          placeholder="关联源事件 ID（可选，留空表示暂无源证）"
        />
        <div class="modal-actions">
          <n-button size="small" quaternary @click="createNodeOpen = false">取消</n-button>
          <n-button
            size="small"
            type="primary"
            :disabled="!createTitle.trim()"
            :loading="creatingNode"
            @click="doCreateNode"
          >
            创建
          </n-button>
        </div>
      </div>
    </n-modal>

    <!-- 建边 -->
    <n-modal :show="createEdgeOpen" @update:show="(v: boolean) => (createEdgeOpen = v)">
      <div class="modal-box">
        <h3 class="modal-title">建边（节点之间的关系）</h3>
        <p class="note">关系从源节点指向目标节点；建议填写证据事件 ID 以保留来源锚定。</p>
        <p v-if="scope.isJoint.value" class="warn-note">
          当前勾选了 {{ scope.selectedIds.value.length }} 本书目（联查 · 只读聚合）：`POST /edges`
          不接受库参数，建边只写进活动书目《{{ write.activeRepoName.value }}》，不会写进联查的其它库。
        </p>
        <n-select
          v-model:value="edgeSource"
          size="small"
          filterable
          :options="nodeOptions"
          placeholder="源节点"
        />
        <n-select
          v-model:value="edgeTarget"
          size="small"
          filterable
          :options="nodeOptions"
          placeholder="目标节点"
        />
        <n-input v-model:value="edgeRelation" size="small" placeholder="关系（如：属于 / 起因 / 补充）" />
        <n-input v-model:value="edgeEvidence" size="small" placeholder="证据事件 ID（可留空）" />
        <div class="modal-actions">
          <n-button size="small" quaternary @click="createEdgeOpen = false">取消</n-button>
          <n-button
            size="small"
            type="primary"
            :disabled="!edgeSource || !edgeTarget || !edgeRelation.trim()"
            :loading="creatingEdge"
            @click="doCreateEdge"
          >
            建边
          </n-button>
        </div>
      </div>
    </n-modal>
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 信息图谱（查阅区）：看衍生知识的关联结构。
 *
 * 数据来源（v1.37）：`GET /nodes`（单库 `repo_id` / 联查 `repo_ids`）+ `GET /edges`
 * （**一次取全边列表**，与节点同一作用域）。此前没有边列表端点，只能逐节点
 * `GET /nodes/{id}` 汇总边——400 节点 ≈ 17 批请求，且任一批失败即静默丢边。
 *
 * 行为要求：三态互斥（有节点时不显示空态）· 失败可见（错误原文常驻）·
 * 删除保护（有有效源证时 409 → 说明影响后带 force 重试）· 清空图层二次确认 ·
 * 跨书目写入先显式切换活动书目（不静默切换）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NInput, NModal, NSelect, useMessage } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import DetailPanel from '@/components/ui/DetailPanel.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import OriginBadge from '@/components/ui/OriginBadge.vue'
import GraphCanvas from '@/components/GraphCanvas.vue'
import * as nodesApi from '@/api/nodes'
import { ApiError } from '@/api/http'
import type { GraphEdge, NodeDetail, NodeListItem, SourceRef } from '@/api/types'
import { useRepoScope } from '@/composables/useRepoScope'
import { useRepoWrite } from '@/composables/useRepoWrite'
import { useUnsavedGuard } from '@/composables/useUnsavedGuard'
import { useSessionStore } from '@/stores/session'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const session = useSessionStore()
const scope = useRepoScope()
const write = useRepoWrite()

/** 节点上限（与画布上限一致）：画布要一次拿全，不做前端分页 */
const NODE_LIMIT = 400
/** 边上限：后端 `GET /edges` 限定 0..5000；节点上限 400 时边通常 <1000 */
const EDGE_LIMIT = 2000

const TYPE_OPTIONS = [
  { label: '系统 system', value: 'system' },
  { label: '交互 interaction', value: 'interaction' },
  { label: '数据 data', value: 'data' },
]

const TYPE_TEXT: Record<string, string> = { system: '系统', interaction: '交互', data: '数据' }
const typeText = (value: string): string => TYPE_TEXT[value] ?? value

// ── 图数据 ──
const allNodes = ref<NodeListItem[]>([])
/** 服务端返回的节点总数（单库 = 真实总数；联查 = 候选池里的数，见 `nodesTruncated` 说明） */
const nodesTotal = ref(0)
/** 只保留**两端都在已加载节点里**的边：画布本来就只画这种边，数字必须与画面一致 */
const edges = ref<GraphEdge[]>([])
/** 服务端返回的边总数与实收条数：用于判断是否被 `limit` 截断（与「画得出几条」是两回事） */
const edgesTotal = ref(0)
const edgesReceived = ref(0)
/** 端点不在已加载节点里的边数（节点被上限截断，或图里残留悬空端点） */
const edgesSkipped = ref(0)
const loading = ref(false)
const error = ref('')
const opError = ref('')
const typeFilter = ref('')
const refreshEpoch = ref(0)
let loadSeq = 0

const edgesTruncated = computed(() => edgesTotal.value > edgesReceived.value)

/**
 * 节点是否被 `limit` 截断（NODE_LIMIT = 400，画布要一次拿全、不做前端分页）。
 *
 * 注意联查态：后端每库只取 `pool = min(max(limit*3, 50), 100)` 个候选，
 * 且 `total` 就是候选池里融合后的条数（`dpim/interface/routers/query.py`），
 * 所以联查态「没检测到截断」也不代表拿到了全部——提示里必须说明这一点。
 */
const nodesTruncated = computed(() => nodesTotal.value > allNodes.value.length)

const filteredNodes = computed(() =>
  typeFilter.value ? allNodes.value.filter((n) => n.node_type === typeFilter.value) : allNodes.value,
)
const filteredEdges = computed(() => {
  if (!typeFilter.value) return edges.value
  const kept = new Set(filteredNodes.value.map((n) => n.node_id))
  return edges.value.filter((e) => kept.has(e.source) && kept.has(e.target))
})

const emptyHint = computed(() =>
  allNodes.value.length
    ? '把类型筛选改回空值（全部）即可看到全部节点。'
    : '到「信息传入」页写入原文，AI 管线会派生出知识节点。',
)
const visibleError = computed(() => opError.value || (allNodes.value.length ? error.value : ''))

async function loadGraph(): Promise<void> {
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    // 节点与边共用同一库作用域（唯一构造点：勾 1 本 → repo_id / 勾 ≥2 本 → repo_ids）
    const scopeArgs = scope.repoParams()
    const res = await nodesApi.listNodes({ limit: NODE_LIMIT, ...scopeArgs })
    // 边：一次列表请求（v1.37 `GET /edges`），不再逐节点取详情汇总
    let edgeItems: GraphEdge[] = []
    let edgeTotal = 0
    try {
      const edgeRes = await nodesApi.listEdges({ limit: EDGE_LIMIT, ...scopeArgs })
      edgeItems = edgeRes.items
      edgeTotal = edgeRes.total
    } catch (e) {
      if (seq !== loadSeq) return
      // 节点已拿到：边失败不把整页判空，但必须可见（此前逐节点汇总失败是静默丢边）
      error.value = `边列表获取失败（图只显示节点、不显示连线）：${(e as Error).message}`
    }
    if (seq !== loadSeq) return
    allNodes.value = res.items
    nodesTotal.value = res.total
    // 画布只画两端都认识的边（GraphCanvas 内部同口径）；这里先滤掉，让工具栏数字 = 实际画出的线
    const known = new Set(res.items.map((n) => n.node_id))
    const drawable = edgeItems.filter((e) => known.has(e.source) && known.has(e.target))
    edgesReceived.value = edgeItems.length
    edgesSkipped.value = edgeItems.length - drawable.length
    edges.value = drawable
    edgesTotal.value = edgeTotal
  } catch (e) {
    if (seq !== loadSeq) return
    error.value = (e as Error).message
    if (allNodes.value.length === 0) edges.value = []
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

/** 刷新 = 重取 + 重布局（主操作） */
async function refreshGraph(): Promise<void> {
  opError.value = ''
  await loadGraph()
  refreshEpoch.value += 1
  if (selectedId.value) await reloadDetail()
}

/** 重新布局：只让画布按现有数据重排，不重取 */
function relayout(): void {
  refreshEpoch.value += 1
}

function dismissError(): void {
  opError.value = ''
  error.value = ''
}

async function retryAfterError(): Promise<void> {
  await refreshGraph()
}

// ── 画布交互 ──
interface EdgeRef {
  source: string
  target: string
  relation: string
}

const selectedId = ref('')
const selectedRepoId = ref('')
const selectedEdge = ref<EdgeRef | null>(null)

function nodeTitle(id: string): string {
  return allNodes.value.find((n) => n.node_id === id)?.title ?? id.slice(0, 8)
}

async function onCanvasSelect(id: string): Promise<void> {
  await selectNode(id, allNodes.value.find((n) => n.node_id === id)?.repo_id)
}

function onSelectEdge(source: string, target: string, relation: string): void {
  selectedEdge.value = { source, target, relation }
}

// ── 节点详情 ──
const detail = ref<NodeDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
let detailSeq = 0

const isSystemNode = computed(() => detail.value?.node_type === 'system')
/** 后端契约保证存在；仍做兜底，避免单条坏数据把整页详情打崩 */
const sourceRefs = computed<SourceRef[]>(() => detail.value?.source_refs ?? [])
const nodeEdges = computed<GraphEdge[]>(() => detail.value?.edges ?? [])
const validRefCount = computed(() => sourceRefs.value.filter((r) => r.valid).length)

async function loadDetail(nodeId: string, repoId?: string): Promise<void> {
  const seq = ++detailSeq
  detailLoading.value = true
  detailError.value = ''
  try {
    const res = await nodesApi.getNode(nodeId, repoId || undefined)
    if (seq !== detailSeq) return
    detail.value = res
  } catch (e) {
    if (seq !== detailSeq) return
    detail.value = null
    detailError.value = (e as Error).message
  } finally {
    if (seq === detailSeq) detailLoading.value = false
  }
}

async function reloadDetail(): Promise<void> {
  if (selectedId.value) await loadDetail(selectedId.value, selectedRepoId.value)
}

async function selectNode(id: string, repoId?: string): Promise<void> {
  selectedId.value = id
  selectedRepoId.value = repoId ?? ''
  selectedEdge.value = null
  editing.value = false
  if (route.query.node !== id) void router.replace({ query: { ...route.query, node: id } })
  await loadDetail(id, selectedRepoId.value)
}

function clearSelection(): void {
  selectedId.value = ''
  selectedRepoId.value = ''
  detail.value = null
  detailError.value = ''
  editing.value = false
  if (route.query.node) void router.replace({ query: {} })
}

// ── 内容修订 ──
const editing = ref(false)
const draftContent = ref('')
const saving = ref(false)

/**
 * 节点「修订」草稿是否**脏**（离开守卫判据）：正在编辑 + 详情还在 + 内容与所选节点原内容不同。
 *
 * 为什么要 `detail !== null` 这一条：详情可能因为换库 / 重取失败被清空（此时编辑框已经不显示了），
 * 若只比字符串就会出现「看不见的草稿」把用户拦在确认框前——守卫只该拦**用户看得见的**未保存编辑。
 */
const editDirty = computed(
  () => editing.value && detail.value !== null && draftContent.value !== detail.value.content,
)

useUnsavedGuard(
  () => editDirty.value,
  '节点「修订」还没保存，离开将丢失这次编辑。确定离开吗？',
)

function startEdit(): void {
  if (!detail.value) return
  draftContent.value = detail.value.content
  editing.value = true
}

async function saveContent(): Promise<void> {
  const id = detail.value?.node_id
  if (!id) return
  saving.value = true
  opError.value = ''
  await runWithScope(selectedRepoId.value, async () => {
    try {
      await nodesApi.putNode(id, draftContent.value)
      editing.value = false
      message.success('节点内容已保存')
      await session.commit()
      await reloadDetail()
    } catch (e) {
      opError.value = (e as Error).message
    }
  })
  saving.value = false
}

// ── 源证管理 ──
const newRefId = ref('')
const addingRef = ref(false)
const removingRefId = ref('')

function canRemoveRef(ref: SourceRef): boolean {
  // 无效源证移除不影响有效源证数；有效源证移除后须仍剩 ≥1 条
  return !ref.valid || validRefCount.value > 1
}

async function addRef(): Promise<void> {
  const id = detail.value?.node_id
  const eventId = newRefId.value.trim()
  if (!id || !eventId) return
  addingRef.value = true
  opError.value = ''
  await runWithScope(selectedRepoId.value, async () => {
    try {
      await nodesApi.addNodeSourceRef(id, eventId)
      newRefId.value = ''
      message.success('源事件已关联到该节点')
      await session.commit()
      await reloadDetail()
    } catch (e) {
      opError.value = (e as Error).message
    }
  })
  addingRef.value = false
}

async function removeRef(eventId: string): Promise<void> {
  const id = detail.value?.node_id
  if (!id) return
  removingRefId.value = eventId
  opError.value = ''
  await runWithScope(selectedRepoId.value, async () => {
    try {
      await nodesApi.removeNodeSourceRef(id, eventId)
      message.success('源证已移除')
      await session.commit()
      await reloadDetail()
    } catch (e) {
      opError.value = (e as Error).message
    }
  })
  removingRefId.value = ''
}

// ── 删除节点（保护 → 409 → force 重试）──
const deleteOpen = ref(false)
const forceOpen = ref(false)
const forceMessage = ref('')
const deleting = ref(false)

function askDeleteNode(): void {
  deleteOpen.value = true
}

async function deleteNode(force: boolean): Promise<void> {
  const id = detail.value?.node_id
  if (!id) return
  deleting.value = true
  opError.value = ''
  // 需要切换活动书目时先收起本确认框：避免两个模态叠在一起
  if (write.needsActivation(selectedRepoId.value)) {
    deleteOpen.value = false
    forceOpen.value = false
  }
  await runWithScope(selectedRepoId.value, async () => {
    try {
      await nodesApi.deleteNode(id, force)
      deleteOpen.value = false
      forceOpen.value = false
      message.success('节点已删除（关联边一并移除）')
      clearSelection()
      await session.commit()
      await loadGraph()
    } catch (e) {
      deleteOpen.value = false
      forceOpen.value = false
      if (!force && e instanceof ApiError && e.status === 409) {
        forceMessage.value = e.message
        forceOpen.value = true
      } else {
        opError.value = (e as Error).message
      }
    }
  })
  deleting.value = false
}

// ── 删除边 ──
const edgeDeleteOpen = ref(false)
const deletingEdge = ref(false)
const pendingEdge = ref<EdgeRef | null>(null)

const edgeDeleteText = computed(() =>
  pendingEdge.value
    ? `${nodeTitle(pendingEdge.value.source)} → ${nodeTitle(pendingEdge.value.target)}：${pendingEdge.value.relation}`
    : '',
)

function askDeleteEdge(edge: EdgeRef): void {
  pendingEdge.value = { source: edge.source, target: edge.target, relation: edge.relation }
  edgeDeleteOpen.value = true
}

async function doDeleteEdge(): Promise<void> {
  const edge = pendingEdge.value
  if (!edge) return
  deletingEdge.value = true
  opError.value = ''
  if (write.needsActivation(selectedRepoId.value)) edgeDeleteOpen.value = false
  await runWithScope(selectedRepoId.value, async () => {
    try {
      await nodesApi.deleteEdge(edge.source, edge.target)
      edgeDeleteOpen.value = false
      selectedEdge.value = null
      message.success('边已删除')
      await session.commit()
      await loadGraph()
      await reloadDetail()
    } catch (e) {
      edgeDeleteOpen.value = false
      opError.value = (e as Error).message
    }
  })
  deletingEdge.value = false
}

// ── 清空图层（危险操作，二次确认）──
const clearOpen = ref(false)
const clearing = ref(false)

async function doClearGraph(): Promise<void> {
  clearing.value = true
  opError.value = ''
  try {
    const res = await nodesApi.clearGraph()
    clearOpen.value = false
    // 后端 message 已含计数、留档 ID 与「事件回到待处理」——直接透出，不另编文案
    if (res.archived) {
      message.success(res.message)
    } else {
      // 留档失败 = 这次清空不可恢复：用 error 级提示，别让用户以为还能从回收站找回来
      message.error(res.message)
    }
    clearSelection()
    await session.commit()
    await loadGraph()
    refreshEpoch.value += 1
  } catch (e) {
    clearOpen.value = false
    opError.value = (e as Error).message
  } finally {
    clearing.value = false
  }
}

// ── 新建节点 / 建边 ──
const createNodeOpen = ref(false)
const creatingNode = ref(false)
const createTitle = ref('')
const createContent = ref('')
const createSourceEvent = ref('')

const createEdgeOpen = ref(false)
const creatingEdge = ref(false)
const edgeSource = ref<string | null>(null)
const edgeTarget = ref<string | null>(null)
const edgeRelation = ref('')
const edgeEvidence = ref('')

const nodeOptions = computed(() =>
  allNodes.value.map((n) => ({ label: `${n.title}（${typeText(n.node_type)}）`, value: n.node_id })),
)
const writeTargetName = computed(
  () =>
    `活动书目《${write.activeRepoName.value}》${scope.isJoint.value ? '（当前为联查：写入只作用于活动书目）' : ''}`,
)

function openCreateNode(): void {
  createTitle.value = ''
  createContent.value = ''
  createSourceEvent.value = ''
  createNodeOpen.value = true
}

async function doCreateNode(): Promise<void> {
  const title = createTitle.value.trim()
  if (!title) return
  creatingNode.value = true
  opError.value = ''
  try {
    const res = await nodesApi.createNode(title, createContent.value, createSourceEvent.value.trim())
    createNodeOpen.value = false
    message.success('节点已创建')
    await session.commit()
    await loadGraph()
    // `POST /nodes` 不接受 repo 参数 → 节点建在**活动书目**（弹窗也这么写），
    // 详情必须按写入库查；按顶栏作用域查会在「作用域库 ≠ 活动库」时报 Node not found，
    // 刚建成功的节点看起来失败了，用户会重复建。
    await selectNode(res.node_id, write.activeRepoId.value || undefined)
  } catch (e) {
    opError.value = (e as Error).message
  } finally {
    creatingNode.value = false
  }
}

function openCreateEdge(): void {
  edgeSource.value = null
  edgeTarget.value = null
  edgeRelation.value = ''
  edgeEvidence.value = ''
  createEdgeOpen.value = true
}

async function doCreateEdge(): Promise<void> {
  if (!edgeSource.value || !edgeTarget.value || !edgeRelation.value.trim()) return
  creatingEdge.value = true
  opError.value = ''
  try {
    await nodesApi.createEdge(
      edgeSource.value,
      edgeTarget.value,
      edgeRelation.value.trim(),
      edgeEvidence.value.trim(),
    )
    createEdgeOpen.value = false
    message.success('边已创建')
    await session.commit()
    await loadGraph()
    await reloadDetail()
  } catch (e) {
    opError.value = (e as Error).message
  } finally {
    creatingEdge.value = false
  }
}

// ── 跨书目写入守卫 ──
const activateOpen = ref(false)
const activating = ref(false)
const activateImpacts = ref<string[]>([])
let pendingAction: (() => Promise<void>) | null = null

async function runWithScope(repoId: string | undefined, action: () => Promise<void>): Promise<void> {
  if (!write.needsActivation(repoId)) {
    await action()
    return
  }
  activateImpacts.value = write.activationImpacts(repoId as string)
  pendingAction = async () => {
    await write.activate(repoId as string)
    await action()
  }
  activateOpen.value = true
}

async function confirmActivate(): Promise<void> {
  activating.value = true
  try {
    await pendingAction?.()
    activateOpen.value = false
    await loadGraph()
    await reloadDetail()
  } catch (e) {
    opError.value = (e as Error).message
  } finally {
    pendingAction = null
    activating.value = false
  }
}

// ── 跳转 ──
function jumpEvent(eventId: string): void {
  void router.push({ name: 'events', query: { event: eventId } })
}

// ── 作用域 / 深链：勾选集合变化 → 重取（`scopeKey` 是集合的稳定指纹） ──
watch(scope.scopeKey, async () => {
  await loadGraph()
  refreshEpoch.value += 1
  if (!selectedId.value) return
  const still = allNodes.value.find((n) => n.node_id === selectedId.value)
  if (still) {
    selectedRepoId.value = still.repo_id ?? ''
    await reloadDetail()
  } else {
    clearSelection()
  }
})

watch(
  () => route.query.node,
  (value) => {
    if (typeof value === 'string' && value && value !== selectedId.value) {
      void selectNode(value, allNodes.value.find((n) => n.node_id === value)?.repo_id)
    }
  },
)

onMounted(async () => {
  await loadGraph()
  const target = route.query.node
  if (typeof target === 'string' && target) {
    await selectNode(target, allNodes.value.find((n) => n.node_id === target)?.repo_id)
  }
})
</script>

<style scoped>
.split {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr);
  gap: var(--dpim-space-3);
}
/* 画布槽：底色由 GraphCanvas 自带（令牌 --dpim-bg + 网格点） */
.canvas-card {
  position: relative;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  overflow: hidden;
}
.detail-wrap {
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.f-select {
  width: calc(var(--dpim-space-7) * 3);
}
.tool-meta,
.scope-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  white-space: nowrap;
}
.note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.45;
}
/* 联查态下的写动作警告（口径与 StorageCheckPage 的 warn-note 一致） */
.warn-note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-warning);
  line-height: 1.5;
}

/* 错误常驻条（P6 失败可见） */
.error-strip {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-danger-soft);
  border: var(--dpim-hairline) solid var(--dpim-danger);
  border-radius: var(--dpim-radius-sm);
}
.error-text {
  flex: 1;
  min-width: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-danger);
  word-break: break-word;
}

/* 图例 */
.legend {
  position: absolute;
  left: var(--dpim-space-3);
  bottom: var(--dpim-space-3);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--dpim-space-1) var(--dpim-space-3);
  max-width: calc(100% - var(--dpim-space-6));
  padding: var(--dpim-space-1) var(--dpim-space-3);
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-xs);
  box-shadow: var(--dpim-shadow-sm);
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
  pointer-events: none;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: var(--dpim-space-1);
}
.legend-item--dim {
  color: var(--dpim-text-3);
}
.legend-dot {
  width: var(--dpim-space-2);
  height: var(--dpim-space-2);
  border-radius: 50%;
  flex-shrink: 0;
}
.legend-dot--system {
  background: var(--dpim-primary);
}
.legend-dot--interaction {
  background: var(--dpim-success);
}
.legend-dot--data {
  background: var(--dpim-info);
}

/* 选中边 */
.edge-chip {
  position: absolute;
  right: var(--dpim-space-3);
  bottom: var(--dpim-space-3);
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  max-width: calc(100% - var(--dpim-space-6));
  padding: var(--dpim-space-1) var(--dpim-space-2);
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-xs);
  box-shadow: var(--dpim-shadow-sm);
}
.edge-chip-text {
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 详情分节 */
.block {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
}
.block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--dpim-space-2);
  flex-wrap: wrap;
}
.block-title {
  margin: 0;
  font-size: var(--dpim-fs-base);
  font-weight: 600;
  color: var(--dpim-text);
}
.content {
  margin: 0;
  padding: var(--dpim-space-3);
  background: var(--dpim-inset);
  box-shadow: var(--dpim-inset-shadow);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
  font-family: var(--dpim-font-sans);
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: calc(var(--dpim-space-7) * 8);
  overflow: auto;
}
.row-actions {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
}

/* 源证 */
.ref-list,
.edge-list {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
}
.ref-row,
.edge-row {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-1) 0;
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
}
.ref-row:last-child,
.edge-row:last-child {
  border-bottom: none;
}
.mono {
  flex: 1;
  min-width: 0;
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ref-state {
  flex-shrink: 0;
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
}
.ref-state--ok {
  background: var(--dpim-success-soft);
  color: var(--dpim-success);
}
.ref-state--bad {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.ref-add {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
}
.edge-text {
  flex: 1;
  min-width: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text-2);
  word-break: break-word;
}

/* 弹层表单（统一层未提供模态容器：与样板页同一写法） */
.modal-box {
  width: min(calc(var(--dpim-space-7) * 12), calc(100vw - var(--dpim-space-6)));
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-5);
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  box-shadow: var(--dpim-shadow);
}
.modal-title {
  margin: 0;
  font-size: var(--dpim-fs-lg);
  font-weight: 600;
  color: var(--dpim-text);
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--dpim-space-2);
}
</style>
