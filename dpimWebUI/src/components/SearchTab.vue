<template>
  <div class="search-tab">
    <!-- 搜索维度 -->
    <n-tabs
      v-model:value="searchMode"
      type="line"
      size="small"
      :tabs-padding="0"
      @update:value="onModeChange"
    >
      <n-tab-pane name="hybrid" tab="综合检索" />
      <n-tab-pane name="events" tab="事件原文" />
      <n-tab-pane name="nodes" tab="知识节点" />
    </n-tabs>

    <!-- 搜索栏 -->
    <div class="search-bar">
      <n-input
        v-model:value="query"
        :placeholder="placeholderText"
        size="large"
        clearable
        @keyup.enter="doSearch"
        :disabled="loading"
      >
        <template #prefix>
          <n-icon size="16">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          </n-icon>
        </template>
      </n-input>
      <n-select
        v-if="searchMode === 'hybrid'"
        v-model:value="sourceFilter"
        :options="sourceFilterOpts"
        placeholder="类型"
        size="large"
        style="width:130px;flex-shrink:0"
      />
      <n-button
        size="large"
        type="primary"
        @click="doSearch"
        :disabled="!query.trim() && searchMode === 'hybrid'"
        :loading="loading"
        style="flex-shrink:0"
      >
        {{ searchMode === 'hybrid' ? '搜索' : '检索' }}
      </n-button>
    </div>

    <!-- 高级筛选 -->
    <div class="filter-bar">
      <n-button size="tiny" quaternary @click="showFilters = !showFilters">
        <template #icon>
          <n-icon size="14">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z"/>
            </svg>
          </n-icon>
        </template>
        {{ showFilters ? '收起高级筛选' : '展开高级筛选' }}
      </n-button>
    </div>

    <n-collapse-transition :show="showFilters">
      <div class="filter-panel">
        <template v-if="searchMode === 'hybrid'">
          <div class="filter-row">
            <span class="filter-label">来源类型</span>
            <n-select v-model:value="sourceFilter" :options="sourceFilterOpts" style="width:120px" />
          </div>
          <div class="filter-row">
            <span class="filter-label">图扩散跳数</span>
            <n-slider v-model:value="maxHops" :min="0" :max="5" :step="1" style="width:140px" />
            <span class="filter-value">{{ maxHops }}</span>
          </div>
          <div class="filter-row">
            <span class="filter-label">结果数量</span>
            <n-select v-model:value="resultLimit" :options="limitOpts" style="width:100px" />
          </div>
        </template>

        <template v-if="searchMode === 'events'">
          <div class="filter-row">
            <span class="filter-label">事件状态</span>
            <n-select v-model:value="eventStatus" :options="statusOpts" style="width:120px" clearable />
          </div>
          <div class="filter-row">
            <span class="filter-label">最低置信度</span>
            <n-slider v-model:value="minConfidence" :min="0" :max="1" :step="0.05" style="width:140px" />
            <span class="filter-value">{{ minConfidence.toFixed(2) }}</span>
          </div>
          <div class="filter-row">
            <span class="filter-label">结果数量</span>
            <n-select v-model:value="resultLimit" :options="limitOpts" style="width:100px" />
          </div>
        </template>

        <template v-if="searchMode === 'nodes'">
          <div class="filter-row">
            <span class="filter-label">最低置信度</span>
            <n-slider v-model:value="minConfidence" :min="0" :max="1" :step="0.05" style="width:140px" />
            <span class="filter-value">{{ minConfidence.toFixed(2) }}</span>
          </div>
          <div class="filter-row">
            <span class="filter-label">结果数量</span>
            <n-select v-model:value="resultLimit" :options="limitOpts" style="width:100px" />
          </div>
        </template>
      </div>
    </n-collapse-transition>

    <!-- 统计栏 -->
    <div v-if="searched" class="search-stats">
      <span class="stats-text">
        共 {{ realTotal }} 条结果
        <span v-if="totalPages > 1" class="page-indicator">，第 {{ currentPage }}/{{ totalPages }} 页</span>
        <template v-if="searchMode === 'hybrid'">
          <n-tag v-if="degraded" size="tiny" type="warning" :bordered="false" style="margin-left:6px">降级模式（仅关键词）</n-tag>
          <n-tag v-else size="tiny" type="success" :bordered="false" style="margin-left:6px">混合检索（关键词 + 图扩散）</n-tag>
        </template>
        <n-tag v-else size="tiny" type="info" :bordered="false" style="margin-left:6px">
          {{ searchMode === 'events' ? '事件原文' : '知识节点' }}
        </n-tag>
      </span>
      <n-button size="tiny" quaternary @click="clearResults">清除结果</n-button>
    </div>

    <!-- 结果区 -->
    <div class="search-results" v-if="results.length > 0">
      <!-- 综合检索 — 按类型分组展示 -->
      <template v-if="searchMode === 'hybrid'">
        <div v-for="(group, type) in groupedResults" :key="type" class="result-group">
          <div class="group-header">
            <span class="group-icon">{{ groupIcon(type) }}</span>
            <span class="group-label">{{ groupLabel(type) }}</span>
            <span class="group-count">{{ group.length }}</span>
          </div>
          <div v-for="r in group" :key="r.node_id" class="result-card" @click="onViewNode(r)">
            <div class="card-header">
              <span class="card-title" :title="r.title">{{ r.title }}</span>
              <n-tag size="tiny" :bordered="false" :type="sourceTagType(r.source_type)">{{ r.source_type }}</n-tag>
              <span class="card-score">RRF {{ r.score.toFixed(3) }}</span>
            </div>
            <div class="card-snippet">{{ r.snippet }}</div>
            <div class="card-footer">
              <div class="footer-left">
                <span class="card-conf">置信度 {{ (r.confidence || 0).toFixed(2) }}</span>
                <span v-if="r.source_events && r.source_events.length" class="card-events" :title="r.source_events.join('\n')">源事件 {{ r.source_events.length }}</span>
              </div>
              <div class="footer-actions">
                <n-button size="tiny" :type="feedbackState[r.node_id] === 'accepted' ? 'success' : 'default'" secondary :disabled="!!feedbackState[r.node_id]" @click.stop="onFeedback(r.node_id, true)">有用</n-button>
                <n-button size="tiny" :type="feedbackState[r.node_id] === 'rejected' ? 'error' : 'default'" secondary :disabled="!!feedbackState[r.node_id]" @click.stop="onFeedback(r.node_id, false)">无用</n-button>
                <n-button size="tiny" quaternary @click.stop="onViewNode(r)">查看节点</n-button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 事件原文 / 知识节点 — 平铺列表 -->
      <template v-else>
        <div v-for="r in results" :key="r.node_id" class="result-card" @click="onViewNode(r)">
          <div class="card-header">
            <span class="card-title" :title="r.title">{{ r.title }}</span>
            <n-tag size="tiny" :bordered="false" :type="sourceTagType(r.source_type)">{{ r.source_type }}</n-tag>
            <span v-if="r.score > 0" class="card-score">RRF {{ r.score.toFixed(3) }}</span>
          </div>
          <div class="card-snippet">{{ r.snippet }}</div>
          <div class="card-footer">
            <div class="footer-left">
              <span class="card-conf">置信度 {{ (r.confidence || 0).toFixed(2) }}</span>
              <span v-if="r.source_events && r.source_events.length" class="card-events" :title="r.source_events.join('\n')">源事件 {{ r.source_events.length }}</span>
            </div>
            <div class="footer-actions">
              <n-button size="tiny" :type="feedbackState[r.node_id] === 'accepted' ? 'success' : 'default'" secondary :disabled="!!feedbackState[r.node_id]" @click.stop="onFeedback(r.node_id, true)">有用</n-button>
              <n-button size="tiny" :type="feedbackState[r.node_id] === 'rejected' ? 'error' : 'default'" secondary :disabled="!!feedbackState[r.node_id]" @click.stop="onFeedback(r.node_id, false)">无用</n-button>
              <n-button size="tiny" quaternary @click.stop="onViewNode(r)">查看节点</n-button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- 分页 -->
    <div v-if="searched && totalPages > 1" class="pagination-bar">
      <n-button size="tiny" @click="goToPage(currentPage - 1)" :disabled="currentPage <= 1">上一页</n-button>
      <span class="page-num">{{ currentPage }} / {{ totalPages }}</span>
      <n-button size="tiny" @click="goToPage(currentPage + 1)" :disabled="currentPage >= totalPages">下一页</n-button>
    </div>

    <!-- 空状态 -->
    <div class="empty-area" v-if="!loading">
      <n-empty v-if="searched && results.length === 0" description="无匹配结果" size="small">
        <template #extra>
          <n-button size="small" @click="clearResults">清除条件重试</n-button>
        </template>
      </n-empty>
      <n-empty v-else-if="!searched" :description="emptyDescription" size="small">
        <template #extra v-if="searchMode !== 'hybrid'">
          <n-button size="small" @click="browseRecent">浏览最近{{ searchMode === 'events' ? '事件' : '节点' }}</n-button>
        </template>
      </n-empty>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-area">
      <n-spin size="small" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import * as api from '@/api/client'
import type { SearchResult } from '@/api/client'
import { useMessage } from 'naive-ui'

const message = useMessage()

// ── 状态 ──
const searchMode = ref<'hybrid' | 'events' | 'nodes'>('hybrid')
const query = ref('')
const loading = ref(false)
const searched = ref(false)
const showFilters = ref(false)
const realTotal = ref(0)
const degraded = ref(false)

// 筛选参数
const sourceFilter = ref('all')
const maxHops = ref(2)
const resultLimit = ref(20)
const eventStatus = ref('')
const minConfidence = ref(0)

// 分页
const currentPage = ref(1)

/** 后端实际返回的总条数（分页前） */
const totalPages = computed(() => Math.max(1, Math.ceil(realTotal.value / resultLimit.value)))

// 结果 + 反馈
const results = ref<SearchResult[]>([])
const feedbackState = reactive<Record<string, 'accepted' | 'rejected'>>({})

// ── 选项 ──
const sourceFilterOpts = [
  { label: '全部', value: 'all' },
  { label: 'interaction', value: 'interaction' },
  { label: 'data', value: 'data' },
  { label: 'system', value: 'system' },
]

const limitOpts = [
  { label: '10', value: 10 },
  { label: '20', value: 20 },
  { label: '50', value: 50 },
  { label: '100', value: 100 },
]

const statusOpts = [
  { label: '全部', value: '' },
  { label: '待处理', value: 'pending' },
  { label: '有效', value: 'valid' },
  { label: '失效', value: 'invalid' },
]

// ── 计算属性 ──
const placeholderText = computed(() => {
  switch (searchMode.value) {
    case 'hybrid': return '输入关键词搜索事件原文与知识节点…'
    case 'events': return '输入关键词在事件原文中检索…'
    case 'nodes': return '输入关键词在知识节点中检索…'
  }
})

const emptyDescription = computed(() => {
  switch (searchMode.value) {
    case 'hybrid': return '输入关键词开始搜索'
    case 'events': return '输入关键词检索事件原文，或浏览最近事件'
    case 'nodes': return '输入关键词检索知识节点，或浏览最近节点'
  }
})

/** 综合检索模式下按 source_type 分组 */
const groupedResults = computed(() => {
  const groups: Record<string, SearchResult[]> = {}
  for (const r of results.value) {
    const key = r.source_type || 'unknown'
    if (!groups[key]) groups[key] = []
    groups[key].push(r)
  }
  return groups
})

// ── 辅助函数 ──
function groupIcon(type: string): string {
  if (type === 'interaction') return '◆'
  if (type === 'data') return '■'
  if (type === 'system') return '▲'
  return '●'
}
function groupLabel(type: string): string {
  if (type === 'interaction') return '事件原文'
  if (type === 'data') return '知识节点'
  if (type === 'system') return '系统事件'
  return type
}
function sourceTagType(t: string) {
  if (t === 'interaction') return 'success'
  if (t === 'data') return 'warning'
  return 'info'
}

// ── 核心搜索 ──
async function doSearch() {
  if (searchMode.value === 'hybrid' && !query.value.trim()) return
  if (!query.value.trim()) return

  // 将页码重置为 1（非翻页触发的全新搜索）
  currentPage.value = 1
  await fetchPage(1)
}

/** 根据页码加载数据（翻页或首次搜索共用） */
async function fetchPage(page: number) {
  searched.value = true
  loading.value = true

  try {
    const limit = resultLimit.value
    const params: Record<string, any> = {
      query: query.value,
      limit,
      offset: (page - 1) * limit,
    }

    if (searchMode.value === 'hybrid') {
      params.source_filter = sourceFilter.value
      params.max_hops = maxHops.value
    } else if (searchMode.value === 'events') {
      params.source_filter = 'interaction'
      params.max_hops = 0
    } else {
      params.source_filter = 'data'
      params.max_hops = 0
    }

    const res = await api.query(params)
    realTotal.value = res.total
    degraded.value = res.degraded

    // 客户端置信度过滤（仅影响当前页展示，不影响分页总数）
    let filtered = res.results
    if (minConfidence.value > 0) {
      filtered = filtered.filter(r => (r.confidence || 0) >= minConfidence.value)
    }
    results.value = filtered

    // 清除旧反馈状态
    for (const key of Object.keys(feedbackState)) delete feedbackState[key]
  } catch (e: any) {
    results.value = []
    realTotal.value = 0
    message.error('搜索失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

function onModeChange() {
  clearResults()
}

function clearResults() {
  results.value = []
  searched.value = false
  realTotal.value = 0
  degraded.value = false
  currentPage.value = 1
  for (const key of Object.keys(feedbackState)) delete feedbackState[key]
}

/** 翻页 */
function goToPage(page: number) {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
  fetchPage(page)
}

// ── 浏览最近（无关键词快速浏览） ──
async function browseRecent() {
  loading.value = true
  currentPage.value = 1
  try {
    if (searchMode.value === 'events') {
      const res = await api.listEvents({ limit: resultLimit.value || 20 })
      results.value = res.items.map(ev => ({
        node_id: ev.event_id,
        title: ev.event_id,
        snippet: ev.raw_content.slice(0, 200),
        score: 0,
        source_events: [ev.event_id],
        source_type: ev.event_type,
        confidence: 0.5,
        degraded: false,
      }))
      realTotal.value = res.total
    } else {
      const res = await api.listNodes({ limit: resultLimit.value || 20 })
      const detailPromises = res.items.map(n => api.getNode(n.node_id).catch(() => null))
      const details = await Promise.all(detailPromises)
      results.value = res.items.map((n, i) => {
        const d = details[i]
        return {
          node_id: n.node_id,
          title: n.title,
          snippet: d?.content?.slice(0, 200) || '',
          score: 0,
          source_events: d?.source_refs?.map(sr => sr.event_id) || [],
          source_type: n.node_type,
          confidence: n.confidence,
          degraded: false,
        }
      })
      realTotal.value = res.total
    }
    searched.value = true
  } catch (e: any) {
    results.value = []
    realTotal.value = 0
    message.error('加载失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

// ── 交互 ──
function onViewNode(r: SearchResult) {
  localStorage.setItem('dpim_focus_node', r.node_id)
  window.dispatchEvent(new CustomEvent('dpim:focus-node', { detail: { nodeId: r.node_id } }))
}

async function onFeedback(id: string, accepted: boolean) {
  try {
    await api.postFeedback(id, accepted)
    feedbackState[id] = accepted ? 'accepted' : 'rejected'
  } catch {
    // silent
  }
}
</script>

<style scoped>
.search-tab {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0 24px 12px;
  overflow: hidden;
}

/* 搜索栏 */
.search-bar {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  margin-top: 4px;
}

/* 高级筛选 */
.filter-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  padding: 2px 0;
}
.filter-panel {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 10px 24px;
  padding: 6px 12px;
  margin-bottom: 4px;
  background: rgba(255,255,255,0.04);
  border-radius: 6px;
  border: 1px solid var(--n-border-color);
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.filter-label {
  font-size: 12px;
  color: var(--n-text-color-3);
  white-space: nowrap;
}
.filter-value {
  font-size: 12px;
  color: var(--n-text-color-2);
  min-width: 28px;
  text-align: center;
}

/* 统计栏 */
.search-stats {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 12px;
  color: var(--n-text-color-3);
  border-bottom: 1px solid var(--n-border-color);
  margin-bottom: 6px;
}
.stats-text { display: flex; align-items: center; }

/* 结果区 */
.search-results {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

/* 结果分组 */
.result-group { margin-bottom: 10px; }
.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  margin-bottom: 4px;
  border-radius: 4px;
  background: rgba(255,255,255,0.03);
  border-left: 3px solid var(--n-primary-color);
}
.group-icon { font-size: 13px; }
.group-label { font-size: 13px; font-weight: 600; color: var(--n-text-color-2); }
.group-count {
  font-size: 11px;
  color: var(--n-text-color-3);
  background: rgba(255,255,255,0.08);
  padding: 0 6px;
  border-radius: 8px;
}

/* 结果卡片 */
.result-card {
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.15s;
}
.result-card:hover {
  border-color: var(--n-primary-color);
  background: rgba(255,255,255,0.02);
}
.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
  flex-wrap: wrap;
}
.card-title {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-score {
  color: var(--n-text-color-3);
  font-size: 11px;
  white-space: nowrap;
}
.card-snippet {
  font-size: 13px;
  line-height: 1.5;
  color: var(--n-text-color-2);
  margin-bottom: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px;
}
.footer-left { display: flex; align-items: center; gap: 8px; }
.card-conf { color: var(--n-text-color-3); font-size: 11px; }
.card-events { color: var(--n-text-color-3); font-size: 11px; cursor: help; border-bottom: 1px dotted var(--n-border-color); }
.footer-actions { display: flex; align-items: center; gap: 4px; }

/* 分页栏 */
.pagination-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 8px 0 4px;
  border-top: 1px solid var(--n-border-color);
  margin-top: 4px;
}
.page-num {
  font-size: 12px;
  color: var(--n-text-color-3);
  min-width: 50px;
  text-align: center;
}
.page-indicator {
  color: var(--n-text-color-3);
  font-weight: 500;
}

/* 空/加载 */
.empty-area {
  flex: 1;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
}
.loading-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
