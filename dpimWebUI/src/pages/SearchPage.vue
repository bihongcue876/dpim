<template>
  <PageShell
    zone="查阅"
    title="检索"
    description="跨书目找东西，并看清来自哪本书目、为什么排这里"
  >
    <!-- 唯一主操作（P4）：提交检索 -->
    <template #actions>
      <n-button type="primary" size="small" :loading="loading" @click="doSearch">检索</n-button>
    </template>

    <Toolbar>
      <n-select
        v-model:value="mode"
        size="small"
        class="f-select"
        :options="MODE_OPTIONS"
        @update:value="onModeChange"
      />
      <n-input
        v-model:value="keyword"
        size="small"
        class="f-input"
        :placeholder="placeholder"
        clearable
        @keyup.enter="doSearch"
      />
      <template #right>
        <span class="scope-note">{{ scope.scopeLabel.value }} · 范围由顶栏勾选</span>
        <n-button size="small" quaternary @click="clearResults">清除结果</n-button>
      </template>
    </Toolbar>

    <!-- 高级筛选（书目范围不由本页决定） -->
    <SectionCard title="高级筛选" hint="书目范围由顶栏全局选择器决定，本页只显示当前范围">
      <FieldRow label="来源类型" hint="综合模式按来源类型过滤（交互 / 数据 / 系统）">
        <n-select
          v-model:value="sourceFilter"
          size="small"
          class="f-select"
          :options="SOURCE_OPTIONS"
          :disabled="mode !== 'hybrid'"
        />
      </FieldRow>
      <FieldRow label="图扩散跳数" hint="0 = 不扩散（只做全文检索）；1-5 = 沿衍生知识关联扩散">
        <n-select
          v-model:value="maxHops"
          size="small"
          class="f-select"
          :options="HOP_OPTIONS"
          :disabled="mode !== 'hybrid'"
        />
      </FieldRow>
      <FieldRow label="每页条数" hint="服务端分页（offset）：真分页，不是前端截断">
        <n-select
          :value="pageSize"
          size="small"
          class="f-select"
          :options="LIMIT_OPTIONS"
          @update:value="onLimitChange"
        />
      </FieldRow>
    </SectionCard>

    <!-- 操作失败常驻（P6 失败可见：不只在 toast 里闪一下） -->
    <div v-if="feedbackError" class="error-strip">
      <span class="error-text">反馈失败：{{ feedbackError }}</span>
      <n-button size="tiny" quaternary @click="feedbackError = ''">关闭</n-button>
    </div>

    <div class="result-area">
      <div v-if="searched && !showLoading" class="stat-line">
        <span class="stat-text">共 {{ total }} 条 · 第 {{ page }} / {{ totalPages }} 页</span>
        <span v-if="mode === 'hybrid' && degraded" class="chip chip--warn">
          AI 不可用，已用全文检索
        </span>
        <span v-else-if="mode === 'hybrid'" class="chip chip--ok">混合检索（全文 + 图扩散）</span>
        <span v-else class="chip">
          {{ mode === 'events' ? '原文检索（全文）' : '衍生知识检索（全文）' }}
        </span>
        <span v-if="scope.isJoint.value" class="chip">联查为只读聚合</span>
      </div>

      <!-- 融合轨迹：联查且 trace 非空时显示；默认折叠，不喧宾夺主 -->
      <div v-if="showTrace" class="trace-wrap">
        <SectionCard title="融合轨迹" hint="联查每书目取候选池 → 融合去重 → 分页只切一次">
          <n-collapse>
            <n-collapse-item name="trace" title="展开融合轨迹（每库候选 / 去重 / 各库排名贡献）">
              <div class="trace-stats">
                <span class="trace-stat">候选池：{{ trace?.candidate_pool }} 条</span>
                <span class="trace-stat">去重合并：{{ trace?.deduped }} 条</span>
                <span class="trace-stat">融合后：{{ trace?.merged_total }} 条</span>
                <span class="trace-stat">总耗时：{{ trace?.elapsed_ms }} ms</span>
              </div>
              <p class="trace-label">每书目候选数与耗时</p>
              <DataTable
                :columns="repoColumns"
                :rows="perRepoRows"
                row-key="repo_id"
                empty-text="无每库轨迹"
              />
              <p class="trace-label">本页结果在各书目的排名 / 原始分 / RRF 贡献</p>
              <DataTable
                :columns="hitColumns"
                :rows="contributionRows"
                row-key="id"
                empty-text="无逐条轨迹"
              >
                <template #cell-score="{ value }">{{ fixed(value) }}</template>
                <template #cell-rrf="{ value }">{{ fixed(value) }}</template>
              </DataTable>
            </n-collapse-item>
          </n-collapse>
        </SectionCard>
      </div>

      <!-- 结果卡片：三态互斥——有结果时既不显示空态也不显示加载态 -->
      <div v-if="items.length" class="result-scroll">
        <article v-for="card in items" :key="`${card.kind}:${card.id}`" class="r-card">
          <header class="r-head">
            <span class="r-kind" :class="`r-kind--${card.kind}`">
              {{ card.kind === 'node' ? '衍生知识' : '原文' }}
            </span>
            <span class="r-title" :title="card.title">{{ card.title }}</span>
            <span class="r-type">{{ typeText(card.type) }}</span>
            <span v-if="card.score !== null" class="r-score">RRF {{ card.score.toFixed(3) }}</span>
          </header>

          <p class="r-snippet">{{ card.snippet || '（无片段）' }}</p>

          <div class="r-meta">
            <span class="r-dim">
              置信度 {{ card.confidence === null ? '—（原文无置信度）' : card.confidence.toFixed(2) }}
            </span>
            <span class="r-repo">来自书目《{{ card.repoName || '未知书目' }}》</span>
            <span v-if="card.sourceRepos.length > 1" class="r-dim">
              合并来源：{{ card.sourceRepos.join('、') }}
            </span>
          </div>

          <footer class="r-foot">
            <n-button
              v-if="card.sourceEvents.length"
              size="tiny"
              quaternary
              @click="jumpEvent(card.sourceEvents[0])"
            >
              源事件 {{ card.sourceEvents.length }}
            </n-button>
            <n-button v-if="card.kind === 'node'" size="tiny" quaternary @click="jumpNode(card.id)">
              查看节点
            </n-button>
            <template v-if="card.kind === 'node'">
              <n-button
                size="tiny"
                secondary
                :type="feedbackState[card.id] === true ? 'success' : 'default'"
                :disabled="feedbackState[card.id] !== undefined"
                @click="sendFeedback(card, true)"
              >
                有用
              </n-button>
              <n-button
                size="tiny"
                secondary
                :type="feedbackState[card.id] === false ? 'error' : 'default'"
                :disabled="feedbackState[card.id] !== undefined"
                @click="sendFeedback(card, false)"
              >
                无用
              </n-button>
            </template>
            <span v-else class="r-dim">原文不参与置信度反馈</span>
          </footer>
        </article>
      </div>

      <StateBlock
        v-else
        :loading="showLoading"
        :error="error"
        :empty-text="emptyText"
        :hint="emptyHint"
      >
        <template #retry>
          <n-button size="small" @click="fetchPage">重试</n-button>
        </template>
      </StateBlock>

      <!-- 三模式共用同一个分页条（服务端 offset） -->
      <n-pagination
        v-if="total > pageSize"
        class="pager"
        :page="page"
        :page-size="pageSize"
        :item-count="total"
        :page-slot="7"
        @update:page="onPage"
      />
    </div>
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 检索（查阅区）：跨书目找东西，并看清「来自哪本书目、为什么排这里」。
 *
 * 三模式（共用同一条分页与三态）：
 *   - 综合 hybrid → `POST /query`（带 `repo_ids`，联查融合 + `trace`）
 *   - 原文 events  → `GET /events?query`（全文检索线层原文）
 *   - 节点 nodes   → `GET /nodes?query`（全文检索衍生知识节点）
 *
 * 行为要求：三态互斥（有结果不显示空态/加载态）· 真分页（服务端 offset，分页只切一次）·
 * 联查结果带来源书目 · 跨库反馈带 `repo_id` · 降级明示（AI 不可用 → 全文检索）· 错误原文常驻。
 *
 * 分页自己管 offset（未用 `useListPage`）：三模式 + 轨迹需要**丢弃过期响应**，
 * 否则快速切换模式/书目时，旧响应的结果会覆盖新结果（与链 P10 同类问题）。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton,
  NInput,
  NPagination,
  NSelect,
  NCollapse,
  NCollapseItem,
  useMessage,
} from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import FieldRow from '@/components/ui/FieldRow.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { TableColumn } from '@/components/ui/DataTable.vue'
import * as searchApi from '@/api/search'
import * as eventsApi from '@/api/events'
import * as nodesApi from '@/api/nodes'
import type {
  EventListItem,
  JointTrace,
  NodeListItem,
  SearchResult,
  SourceFilter,
} from '@/api/types'
import { useRepoScope } from '@/composables/useRepoScope'

type Mode = 'hybrid' | 'events' | 'nodes'

/** 结果卡片视图模型：三种模式收敛到同一渲染结构 */
interface ResultCard {
  id: string
  kind: 'node' | 'event'
  title: string
  snippet: string
  score: number | null
  confidence: number | null
  type: string
  repoId: string
  repoName: string
  sourceRepos: string[]
  sourceEvents: string[]
}

/** 一次取数的完整结果（轨迹与降级只在过期检查通过后才落到界面状态） */
interface QueryOutcome {
  items: ResultCard[]
  total: number
  degraded: boolean
  trace: JointTrace | null
}

const router = useRouter()
const message = useMessage()
const scope = useRepoScope()

/** 片段截断长度（展示用，避免卡片过高） */
const SNIPPET_LEN = 240
/** 节点模式补详情时的并发批大小 */
const DETAIL_BATCH = 24

const MODE_OPTIONS = [
  { label: '综合（全文 + 图扩散）', value: 'hybrid' },
  { label: '原文（事件）', value: 'events' },
  { label: '节点（衍生知识）', value: 'nodes' },
]
const SOURCE_OPTIONS = [
  { label: '全部来源', value: 'all' },
  { label: '交互 interaction', value: 'interaction' },
  { label: '数据 data', value: 'data' },
  { label: '系统 system', value: 'system' },
]
const HOP_OPTIONS = [
  { label: '0 · 不扩散', value: 0 },
  { label: '1 跳', value: 1 },
  { label: '2 跳', value: 2 },
  { label: '3 跳', value: 3 },
  { label: '4 跳', value: 4 },
  { label: '5 跳', value: 5 },
]
const LIMIT_OPTIONS = [
  { label: '10 条/页', value: 10 },
  { label: '20 条/页', value: 20 },
  { label: '50 条/页', value: 50 },
  { label: '100 条/页', value: 100 },
]

const TYPE_TEXT: Record<string, string> = {
  system: '系统',
  interaction: '交互',
  data: '数据',
  source: '来源',
}
const typeText = (value: string): string => TYPE_TEXT[value] ?? (value || '未知')

// ── 条件与状态 ──
const mode = ref<Mode>('hybrid')
const keyword = ref('')
/** 本次结果对应的关键词（翻页时复用，避免用到输入框里未提交的改动） */
const activeQuery = ref('')
const sourceFilter = ref<SourceFilter>('all')
const maxHops = ref(2)

const items = ref<ResultCard[]>([])
const total = ref(0)
const offset = ref(0)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')
const searched = ref(false)
const degraded = ref(false)
const trace = ref<JointTrace | null>(null)
const feedbackState = ref<Record<string, boolean>>({})
const feedbackError = ref('')

/** 请求序号：快速切换模式/书目/翻页时丢弃过期响应 */
let fetchSeq = 0

const showLoading = computed(() => loading.value && items.value.length === 0)
const page = computed(() => Math.floor(offset.value / pageSize.value) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const showTrace = computed(() => mode.value === 'hybrid' && trace.value !== null)

const placeholder = computed(() => {
  if (mode.value === 'events') return '输入关键词在原文中检索…'
  if (mode.value === 'nodes') return '输入关键词在衍生知识节点中检索…'
  return '输入关键词检索原文与衍生知识（范围 = 顶栏勾选的书目）…'
})
const emptyText = computed(() => (searched.value ? '没有匹配结果' : '输入关键词开始检索'))
const emptyHint = computed(() =>
  searched.value
    ? '换关键词重试；综合模式可把「图扩散跳数」调为 0（只做全文检索）或调大（沿关联扩散）。'
    : '三种模式：综合（全文 + 图扩散）· 原文（线层事件）· 节点（衍生知识）。书目范围由顶栏决定。',
)

// ── 结果映射 ──
function toHybridCard(result: SearchResult): ResultCard {
  return {
    id: result.node_id,
    kind: result.kind === 'event' ? 'event' : 'node',
    title: result.title,
    snippet: result.snippet,
    score: result.score,
    confidence: result.confidence,
    type: result.source_type,
    repoId: result.repo_id ?? '',
    repoName: result.repo_name ?? '',
    sourceRepos: result.source_repos ?? [],
    sourceEvents: result.source_events ?? [],
  }
}

function toEventCard(item: EventListItem): ResultCard {
  return {
    id: item.event_id,
    kind: 'event',
    title: item.event_id,
    snippet: item.raw_content.slice(0, SNIPPET_LEN),
    score: null,
    confidence: null,
    type: item.event_type,
    repoId: item.repo_id ?? '',
    repoName: item.repo_name ?? '',
    sourceRepos: [],
    sourceEvents: [item.event_id],
  }
}

/** 节点模式：列表项无片段与源证，按批补节点详情 */
async function toNodeCards(list: NodeListItem[]): Promise<ResultCard[]> {
  const cards: ResultCard[] = []
  for (let i = 0; i < list.length; i += DETAIL_BATCH) {
    const batch = list.slice(i, i + DETAIL_BATCH)
    const details = await Promise.all(
      batch.map((n) => nodesApi.getNode(n.node_id, n.repo_id).catch(() => null)),
    )
    batch.forEach((item, index) => {
      const detail = details[index]
      cards.push({
        id: item.node_id,
        kind: 'node',
        title: item.title,
        snippet: (detail?.content ?? '').slice(0, SNIPPET_LEN),
        score: null,
        confidence: item.confidence,
        type: item.node_type,
        repoId: item.repo_id ?? '',
        repoName: item.repo_name ?? '',
        sourceRepos: [],
        sourceEvents: (detail?.source_refs ?? []).map((ref) => ref.event_id),
      })
    })
  }
  return cards
}

// ── 取数 ──
/**
 * 联查参数：`POST /query` 只认 `repo_ids`（列表）。
 * 勾 1 本 → 长度 1 的列表（后端 `len != 1` 才走联查，长度 1 = 指定库检索）；
 * 勾 ≥2 本 → 子集联查。**不传**（没有已加载的库）→ 后端按活动书目。
 */
const queryRepoIds = computed<string[] | undefined>(() => {
  const params = scope.repoParams()
  if (params.repo_ids?.length) return params.repo_ids
  return params.repo_id ? [params.repo_id] : undefined
})

async function runQuery(): Promise<QueryOutcome> {
  if (mode.value === 'hybrid') {
    const res = await searchApi.query({
      query: activeQuery.value,
      source_filter: sourceFilter.value,
      max_hops: maxHops.value,
      limit: pageSize.value,
      offset: offset.value,
      repo_ids: queryRepoIds.value,
    })
    return {
      items: res.results.map(toHybridCard),
      total: res.total,
      degraded: res.degraded,
      trace: res.trace ?? null,
    }
  }
  if (mode.value === 'events') {
    const res = await eventsApi.listEvents({
      query: activeQuery.value,
      limit: pageSize.value,
      offset: offset.value,
      ...scope.repoParams(),
    })
    return { items: res.items.map(toEventCard), total: res.total, degraded: false, trace: null }
  }
  const res = await nodesApi.listNodes({
    query: activeQuery.value,
    limit: pageSize.value,
    offset: offset.value,
    ...scope.repoParams(),
  })
  const cards = await toNodeCards(res.items)
  return { items: cards, total: res.total, degraded: false, trace: null }
}

/** 真分页取数：过期响应直接丢弃，绝不覆盖新结果 */
async function fetchPage(): Promise<void> {
  const seq = ++fetchSeq
  loading.value = true
  error.value = ''
  searched.value = true
  feedbackState.value = {}
  try {
    const outcome = await runQuery()
    if (seq !== fetchSeq) return
    items.value = outcome.items
    total.value = outcome.total
    degraded.value = outcome.degraded
    trace.value = outcome.trace
  } catch (e) {
    if (seq !== fetchSeq) return
    error.value = (e as Error).message
    items.value = []
    total.value = 0
    degraded.value = false
    trace.value = null
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

// ── 检索动作 ──
async function doSearch(): Promise<void> {
  const text = keyword.value.trim()
  if (!text) {
    message.warning('请输入检索关键词')
    return
  }
  activeQuery.value = text
  offset.value = 0
  await fetchPage()
}

function onModeChange(): void {
  resetResults()
  if (keyword.value.trim()) void doSearch()
}

function onLimitChange(value: unknown): void {
  pageSize.value = typeof value === 'number' && value > 0 ? value : 20
  offset.value = 0
  if (searched.value && activeQuery.value) void fetchPage()
}

function onPage(next: number): void {
  offset.value = (next - 1) * pageSize.value
  void fetchPage()
}

/** 结果整体失效（切换模式 / 清除 / 切换书目）：同时作废在途请求 */
function resetResults(): void {
  fetchSeq += 1
  items.value = []
  total.value = 0
  offset.value = 0
  error.value = ''
  searched.value = false
  degraded.value = false
  trace.value = null
  loading.value = false
  feedbackState.value = {}
}

function clearResults(): void {
  keyword.value = ''
  activeQuery.value = ''
  resetResults()
}

// ── 跳转 ──
function jumpEvent(eventId: string): void {
  void router.push({ name: 'events', query: { event: eventId } })
}

function jumpNode(nodeId: string): void {
  void router.push({ name: 'graph', query: { node: nodeId } })
}

// ── 反馈（跨库必须带 repo_id）──
async function sendFeedback(card: ResultCard, accepted: boolean): Promise<void> {
  feedbackError.value = ''
  try {
    await searchApi.postFeedback(
      card.id,
      accepted,
      card.repoId || scope.effectiveRepoId.value || undefined,
    )
    feedbackState.value = { ...feedbackState.value, [card.id]: accepted }
    message.success(accepted ? '已记录：有用' : '已记录：无用')
  } catch (e) {
    feedbackError.value = (e as Error).message
  }
}

// ── 融合轨迹表 ──
const repoColumns: TableColumn[] = [
  { key: 'repo_name', label: '书目', width: 'md' },
  { key: 'candidates', label: '候选数', width: 'sm', align: 'right' },
  { key: 'elapsed_ms', label: '耗时 ms', width: 'sm', align: 'right' },
]
const hitColumns: TableColumn[] = [
  { key: 'result', label: '结果', width: 'auto' },
  { key: 'repo_name', label: '书目', width: 'md' },
  { key: 'rank', label: '排名', width: 'xs', align: 'right' },
  { key: 'score', label: '原始分', width: 'sm', align: 'right' },
  { key: 'rrf', label: 'RRF 贡献', width: 'sm', align: 'right' },
]
const perRepoRows = computed(() => trace.value?.per_repo ?? [])
const contributionRows = computed(() => {
  const current = trace.value
  if (!current) return []
  return current.hits.flatMap((hit) =>
    (hit.contributions ?? []).map((item) => ({
      id: `${hit.node_id}:${item.repo_id}`,
      result: hit.title,
      repo_name: item.repo_name,
      rank: item.rank,
      score: item.score,
      rrf: item.rrf,
    })),
  )
})

function fixed(value: unknown): string {
  return typeof value === 'number' ? value.toFixed(4) : String(value ?? '—')
}

// ── 勾选集合变化：结果与轨迹整体失效 ──
watch(scope.scopeKey, () => {
  resetResults()
  if (keyword.value.trim()) void doSearch()
})
</script>

<style scoped>
.f-select {
  width: calc(var(--dpim-space-7) * 4);
}
.f-input {
  width: calc(var(--dpim-space-7) * 6);
}
.scope-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  white-space: nowrap;
}

/* 操作失败常驻条 */
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

/* 结果区：统计行 / 轨迹 / 结果滚动 / 分页 逐层 flex + min-height:0 */
.result-area {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
}
.stat-line {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--dpim-space-2);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.stat-text {
  color: var(--dpim-text-2);
}
.chip {
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  background: var(--dpim-surface-2);
  color: var(--dpim-text-3);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  white-space: nowrap;
}
.chip--warn {
  background: var(--dpim-warning-soft);
  color: var(--dpim-warning);
}
.chip--ok {
  background: var(--dpim-success-soft);
  color: var(--dpim-success);
}

/* 融合轨迹：展开不压垮结果区 */
.trace-wrap {
  flex-shrink: 0;
  max-height: 45%;
  overflow: auto;
}
.trace-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--dpim-space-2) var(--dpim-space-4);
  margin-bottom: var(--dpim-space-3);
}
.trace-stat {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
}
.trace-label {
  margin: var(--dpim-space-2) 0 var(--dpim-space-1);
  font-size: var(--dpim-fs-sm);
  font-weight: 600;
  color: var(--dpim-text-3);
}

/* 结果卡片 */
.result-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
}
.r-card {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-3) var(--dpim-space-4);
  background: var(--dpim-inset);
  box-shadow: var(--dpim-inset-shadow);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
}
.r-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--dpim-space-2);
}
.r-kind {
  flex-shrink: 0;
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
}
.r-kind--node {
  background: var(--dpim-derived-bg);
  color: var(--dpim-derived-fg);
}
.r-kind--event {
  background: var(--dpim-origin-bg);
  color: var(--dpim-origin-fg);
}
.r-title {
  flex: 1;
  min-width: 0;
  font-size: var(--dpim-fs-base);
  font-weight: 600;
  color: var(--dpim-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.r-type {
  flex-shrink: 0;
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
}
.r-score {
  flex-shrink: 0;
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
}
.r-snippet {
  margin: 0;
  font-size: var(--dpim-fs-md);
  line-height: 1.6;
  color: var(--dpim-text-2);
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.r-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--dpim-space-1) var(--dpim-space-4);
  font-size: var(--dpim-fs-sm);
}
.r-dim {
  color: var(--dpim-text-3);
}
.r-repo {
  color: var(--dpim-text-2);
}
.r-foot {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--dpim-space-2);
  padding-top: var(--dpim-space-1);
  border-top: var(--dpim-hairline) solid var(--dpim-border);
}

/* 分页条：三模式共用，固定在结果区底部 */
.pager {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  padding-top: var(--dpim-space-2);
  border-top: var(--dpim-hairline) solid var(--dpim-border);
}
</style>
