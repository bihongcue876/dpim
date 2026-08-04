<template>
  <div class="ingest-tab">
    <AIStatusBar :health="health" />

    <div class="it-card">
      <div class="it-card-title">内容输入</div>
      <n-input
        v-model:value="content"
        type="textarea"
        :rows="6"
        autosize
        placeholder="粘贴对话记录、搜索结果、文档片段或任意文本内容..."
      />
      <div class="it-controls">
        <n-select
          v-model:value="eventType"
          :options="typeOpts"
          size="small"
          style="width: 200px"
          :render-label="renderTypeLabel"
        />
        <span class="it-count">字符数: {{ content.length }}</span>
      </div>
    </div>

    <div class="it-actions">
      <n-tooltip :disabled="!submitDisabled" trigger="hover">
        <template #trigger>
          <n-button type="primary" :disabled="submitDisabled" :loading="submitting" @click="onSubmit">
            提交处理
          </n-button>
        </template>
        {{ submitDisabledHint }}
      </n-tooltip>
      <n-button :disabled="submitting || content.length === 0" @click="onClear">清空内容</n-button>
      <div class="it-actions-spacer"></div>
      <n-tooltip trigger="hover">
        <template #trigger>
          <n-button secondary :disabled="!aiOk" :loading="compensating" @click="onCompensate">
            补偿积压事件
          </n-button>
        </template>
        将停留在 raw / indexed 的积压事件重新入队，走 Agent 管线处理
      </n-tooltip>
    </div>

    <div class="it-card">
      <IngestHistory :items="history" @select="onSelectEvent" />
    </div>

    <div class="it-card">
      <div class="it-card-title it-log-title">AI 调用日志（最近 {{ llmLogs.length }} 条）</div>
      <div v-if="llmLogs.length === 0" class="it-log-empty">暂无调用记录</div>
      <div v-for="log in llmLogs" :key="log.timestamp + log.role" class="it-log-row">
        <div class="it-log-head">
          <n-tag size="tiny" :bordered="false" :type="log.error ? 'error' : 'info'">{{ log.role }}</n-tag>
          <span class="it-log-model mono">{{ log.model }}</span>
          <span class="it-log-time">{{ fmtLogTime(log.timestamp) }}</span>
          <n-button text size="tiny" class="it-log-toggle" @click="toggleLog(log)">
            {{ expandedLogs.has(log.timestamp) ? '收起 ▲' : '展开 ▼' }}
          </n-button>
        </div>
        <div v-if="expandedLogs.has(log.timestamp)" class="it-log-body">
          <div v-if="log.error" class="it-log-error">✗ {{ log.error }}</div>
          <template v-else>
            <div class="it-log-label">输入</div>
            <pre class="it-log-text mono">{{ log.input || '' }}</pre>
            <div class="it-log-label">输出</div>
            <pre class="it-log-text mono">{{ log.output }}</pre>
          </template>
        </div>
        <div v-else class="it-log-body">
          <div v-if="log.error" class="it-log-error">✗ {{ shortLog(log.error) }}</div>
          <div v-else class="it-log-out mono">{{ shortLog(log.output) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { createDiscreteApi } from 'naive-ui'
import type { HealthResponse, LLMCallLog } from '@/api/client'
import * as api from '@/api/client'
import AIStatusBar from '@/components/AIStatusBar.vue'
import IngestHistory from '@/components/IngestHistory.vue'

const { message } = createDiscreteApi(['message'])

interface HistoryItem {
  event_id: string
  submitted_at: string
  status: string
  node_count?: number
}

const STORAGE_KEY = 'dpim_ingest_history'
const MAX_HISTORY = 10
const POLL_INTERVAL = 5000
// 本地模型慢：管线单事件最多 ~8 次 LLM 调用（Cr1+In1+Gr≤3+Meta≤3），
// 每次最长 666s，轮询窗口放宽到 90 分钟（1080 次 × 5s），避免被误标 timeout
const MAX_POLL_ATTEMPTS = 1080

const content = ref('')
const eventType = ref('auto')
const submitting = ref(false)
const compensating = ref(false)
const health = ref<HealthResponse | null>(null)
const connected = ref(true)
const history = ref<HistoryItem[]>([])
const pollAttempts = ref<Record<string, number>>({})
let healthTimer: number | null = null
let pollTimer: number | null = null
let logTimer: number | null = null

const llmLogs = ref<LLMCallLog[]>([])
// 展开状态以日志时间戳为键：5s 轮询刷新后索引会位移，时间戳保持稳定
const expandedLogs = ref<Set<number>>(new Set())

function toggleLog(log: LLMCallLog) {
  const next = new Set(expandedLogs.value)
  if (next.has(log.timestamp)) next.delete(log.timestamp)
  else next.add(log.timestamp)
  expandedLogs.value = next
}

async function loadLogs() {
  try {
    const r = await api.getAgentLogs(30, true)
    llmLogs.value = r.logs
  } catch { /* 忽略 */ }
}
function fmtLogTime(ts: number): string {
  const d = new Date(ts * 1000)
  if (isNaN(d.getTime())) return ''
  return d.toTimeString().slice(0, 8)
}
function shortLog(s: string): string {
  return (s || '').slice(0, 400)
}

const aiOk = computed(() => Boolean(health.value?.ai_available))
const submitDisabled = computed(() => submitting.value || !content.value.trim() || !aiOk.value)
const submitDisabledHint = computed(() => {
  if (!aiOk.value) return 'AI 服务未连接，无法提交'
  if (!content.value.trim()) return '请输入内容'
  return ''
})

const typeOpts = [
  { label: 'auto（AI 自动分类）', value: 'auto' },
  { label: 'interaction（对话/决策）', value: 'interaction' },
  { label: 'data（事实资料）', value: 'data' },
  { label: 'source（原始数据，仅存储）', value: 'source' },
]

function renderTypeLabel(option: { label?: string; value: string }) {
  const map: Record<string, string> = {
    auto: 'auto — AI 自动分类',
    interaction: 'interaction — 对话记录、决策过程',
    data: 'data — 事实资料、引用来源',
    source: 'source — 原始数据（仅存储，不进图谱）',
  }
  return map[option.value] ?? String(option.label ?? option.value)
}

// ── localStorage 持久化 ──

function persist() {
  const slim = history.value.map(({ event_id, submitted_at }) => ({ event_id, submitted_at }))
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(slim))
  } catch { /* 忽略存储失败 */ }
}

function restore() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw) as Array<{ event_id: string; submitted_at: string }>
    if (!Array.isArray(parsed)) return
    history.value = parsed.map(h => ({ ...h, status: 'processing' }))
    pollAttempts.value = {}
  } catch { /* 解析失败忽略 */ }
}

// ── 健康检查轮询 ──

async function loadHealth() {
  try {
    health.value = await api.getHealth()
    connected.value = true
  } catch {
    connected.value = false
  }
}

// ── 状态轮询 ──

async function refreshPending() {
  const terminal = new Set(['linked', 'failed', 'skipped', 'timeout'])
  let changed = false
  for (const h of history.value) {
    if (terminal.has(h.status)) continue
    const n = pollAttempts.value[h.event_id] ?? 0
    if (n >= MAX_POLL_ATTEMPTS) {
      h.status = 'timeout'
      changed = true
      continue
    }
    pollAttempts.value[h.event_id] = n + 1
    try {
      const ev = (await api.getEvent(h.event_id)) as Record<string, unknown>
      const st = String(ev.status ?? '')
      if (st === 'linked') {
        const refs = ev.graph_refs
        h.status = 'linked'
        h.node_count = Array.isArray(refs) ? refs.length : 0
        changed = true
      } else if (st === 'failed' || st === 'skipped') {
        h.status = st
        changed = true
      } else {
        h.status = 'indexed'
      }
    } catch { /* 网络错误，保持当前状态继续轮询 */ }
  }
  if (changed) persist()
}

function startPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(refreshPending, POLL_INTERVAL)
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

// ── 动作 ──

async function onSubmit() {
  if (submitDisabled.value) return
  submitting.value = true
  try {
    const res = await api.ingest(content.value, eventType.value)
    const item: HistoryItem = {
      event_id: res.event_id,
      submitted_at: new Date().toISOString(),
      status: 'processing',
    }
    history.value.unshift(item)
    if (history.value.length > MAX_HISTORY) history.value.splice(MAX_HISTORY)
    pollAttempts.value[res.event_id] = 0
    persist()
    content.value = ''
    message.success('已提交，开始处理')
    startPolling()
  } catch (e: any) {
    message.error('提交失败: ' + (e?.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}

function onClear() {
  content.value = ''
}

/** 手动补偿：把 raw/indexed 积压事件重新入队走 Agent 管线 */
async function onCompensate() {
  compensating.value = true
  try {
    await api.compensate()
    message.success('已触发补偿，积压事件开始重新入队处理')
    startPolling()
  } catch (e: any) {
    message.error('补偿触发失败: ' + (e?.message || '未知错误'))
  } finally {
    compensating.value = false
  }
}

function onSelectEvent(eventId: string) {
  window.dispatchEvent(new CustomEvent('dpim:focus-event', { detail: { event_id: eventId } }))
}

// ── 生命周期 ──

onMounted(() => {
  loadHealth()
  restore()
  startPolling()
  loadLogs()
  healthTimer = window.setInterval(loadHealth, 30000)
  logTimer = window.setInterval(loadLogs, 5000)
})

onUnmounted(() => {
  stopPolling()
  if (healthTimer) window.clearInterval(healthTimer)
  if (logTimer) window.clearInterval(logTimer)
})
</script>

<style scoped>
.ingest-tab {
  height: 100%; overflow-y: auto; padding: 16px 24px;
  display: flex; flex-direction: column; gap: 14px;
}
.it-card {
  border: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  border-radius: var(--dpim-radius, 12px);
  background: var(--dpim-surface, #161b22);
  padding: 14px 16px;
}
.it-card-title { font-size: 13px; font-weight: 600; margin-bottom: 10px; color: var(--dpim-text, #e6edf3); letter-spacing: 0.3px; }
.it-controls { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; flex-wrap: wrap; gap: 10px; }
.it-count { font-size: 12px; color: var(--dpim-text-3, #7c8694); font-family: 'Cascadia Code', Consolas, monospace; }
.it-actions { display: flex; gap: 12px; align-items: center; }
.it-actions-spacer { flex: 1; }
.it-log-title { display: flex; align-items: center; }
.it-log-empty { font-size: 12px; color: var(--dpim-text-3, #7c8694); padding: 12px 0; text-align: center; }
.it-log-row { display: flex; align-items: flex-start; gap: 8px; padding: 8px 2px; font-size: 12px; border-bottom: 1px dashed var(--dpim-border, rgba(255,255,255,0.07)); flex-wrap: wrap; }
.it-log-row:last-child { border-bottom: none; }
.it-log-head { display: flex; align-items: center; gap: 8px; width: 100%; }
.it-log-model { color: var(--dpim-text-3, #7c8694); flex-shrink: 0; }
.it-log-time { color: var(--dpim-text-3, #7c8694); font-size: 11px; flex-shrink: 0; }
.it-log-toggle { margin-left: auto; flex-shrink: 0; color: var(--dpim-primary, #5b8cff); }
.it-log-body { width: 100%; }
.it-log-error { color: #f08080; word-break: break-all; white-space: pre-wrap; }
.it-log-out { color: var(--dpim-text-2, #aab4c0); word-break: break-all; white-space: pre-wrap; }
.it-log-label { font-size: 11px; color: var(--dpim-text-3, #7c8694); margin: 6px 0 2px; letter-spacing: 0.5px; }
.it-log-text { color: var(--dpim-text-2, #aab4c0); font-size: 11.5px; line-height: 1.55; margin: 0; padding: 6px 8px; background: rgba(0,0,0,0.22); border-radius: 6px; word-break: break-all; white-space: pre-wrap; max-height: 40vh; overflow-y: auto; }
.mono { font-family: 'Cascadia Code', Consolas, monospace; }
</style>
