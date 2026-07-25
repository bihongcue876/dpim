<template>
  <div class="search-tab">
    <!-- 搜索区 -->
    <div class="search-bar">
      <n-input v-model:value="query" placeholder="输入关键词搜索…" size="large" clearable @keyup.enter="doSearch" />
      <n-select v-model:value="filter" :options="filterOpts" placeholder="类型" size="large" style="width:140px" />
      <n-button size="large" type="primary" @click="doSearch" :disabled="!query.trim()" :loading="loading">搜索</n-button>
    </div>
    <!-- 结果区 -->
    <div class="search-results" v-if="results.length > 0 || loading">
      <div v-for="r in results" :key="r.node_id" class="result-card">
        <div class="card-header">
          <span class="card-title">{{ r.title }}</span>
          <span class="card-score">得分 {{ r.score.toFixed(3) }}</span>
          <n-tag size="tiny" :bordered="false">{{ r.source_type }}</n-tag>
        </div>
        <div class="card-snippet">{{ r.snippet }}</div>
        <div class="card-footer">
          <span class="card-conf">置信度 {{ r.confidence.toFixed(2) }}</span>
          <n-button size="tiny" quaternary @click="feedback(r.node_id, true)">有用</n-button>
          <n-button size="tiny" quaternary @click="feedback(r.node_id, false)">无用</n-button>
        </div>
      </div>
    </div>
    <n-empty v-else-if="searched" description="无匹配结果" size="small" style="padding:80px" />
    <n-empty v-else description="输入关键词开始搜索" size="small" style="padding:80px" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import * as api from '@/api/client'
import type { SearchResult } from '@/api/client'

const query = ref('')
const filter = ref('all')
const results = ref<SearchResult[]>([])
const loading = ref(false)
const searched = ref(false)

const filterOpts = [
  { label: '全部', value: 'all' },
  { label: 'interaction', value: 'interaction' },
  { label: 'data', value: 'data' },
]

async function doSearch() {
  if (!query.value.trim()) return
  searched.value = true
  loading.value = true
  try {
    const res = await api.query({ query: query.value, source_filter: filter.value })
    results.value = res.results
  } catch { /* ignore */ }
  finally { loading.value = false }
}

async function feedback(id: string, accepted: boolean) {
  try {
    await api.postFeedback(id, accepted)
  } catch { /* ignore */ }
}
</script>

<style scoped>
.search-tab { height: 100%; display: flex; flex-direction: column; padding: 16px 24px; overflow: hidden; }
.search-bar { display: flex; gap: 8px; margin-bottom: 16px; flex-shrink: 0; }
.search-results { flex: 1; overflow-y: auto; }
.result-card {
  border: 1px solid var(--n-border-color); border-radius: 6px; padding: 12px; margin-bottom: 10px;
}
.card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.card-title { font-weight: 600; font-size: 14px; flex: 1; }
.card-score { color: var(--n-text-color-3); font-size: 12px; }
.card-snippet { font-size: 13px; line-height: 1.5; color: var(--n-text-color-2); margin-bottom: 8px; }
.card-footer { display: flex; align-items: center; gap: 8px; }
.card-conf { color: var(--n-text-color-3); font-size: 12px; flex: 1; }
</style>
