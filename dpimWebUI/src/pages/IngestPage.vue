<template>
  <PageShell zone="写入" title="信息传入" description="手工贮存原文与发送指令">
    <!-- 本页唯一主操作：提交（P4） -->
    <template #actions>
      <n-button
        type="primary"
        size="small"
        :loading="submitting"
        :disabled="!content.trim()"
        @click="submit"
      >
        提交
      </n-button>
    </template>

    <div class="ingest-scroll">
      <!-- AI 状态行（模型 / 地址 / 上次检查）：AI 不可用**不**禁用提交（规约 §5.5） -->
      <SectionCard
        title="AI 状态"
        hint="AI 未配置或连不上都不影响写入：纯存储与确定层指令照常执行，语义层指令会返回原因"
      >
        <div class="rows">
          <div class="row-item">
            <span class="row-label">AI 管线</span>
            <span class="row-value" :class="health.aiStatus === 'ready' ? 'ok' : 'warn'">
              {{ health.aiStatusText }}
            </span>
          </div>
          <div v-if="health.aiReason" class="row-item">
            <span class="row-label">原因</span>
            <span class="row-value warn">{{ health.aiReason }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">提供商</span>
            <span class="row-value mono">{{ providerName }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">模型</span>
            <span class="row-value mono">{{ modelName }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">地址</span>
            <span class="row-value mono">{{ baseUrl || '—' }}</span>
          </div>
          <!-- 配置读取失败必须与「根本没配 AI」分开：旧状是失败时也全显示「—」，
               与「未配置」同形（上一行甚至可能同时写着「AI 就绪」），用户看不出是读不到 -->
          <div v-if="settingsError" class="row-item">
            <span class="row-label">配置读取</span>
            <span class="row-value bad">
              读取失败：{{ settingsError }}
              （上面三项显示「—」是没读到，不是「没配」）
            </span>
            <n-button size="tiny" :loading="settingsLoading" @click="loadSettings">重试</n-button>
          </div>
          <div class="row-item">
            <span class="row-label">上次检查</span>
            <span class="row-value">{{ checkedText }}</span>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="内容"
        hint="输入 ^ 自动弹出指令候选：↑↓ 选择，Enter / Tab 确认，Esc 收起"
      >
        <Toolbar>
          <n-select
            v-model:value="eventType"
            size="small"
            class="f-type"
            :options="TYPE_OPTIONS"
          />
          <span class="scope-note">写入书目：{{ targetName }}</span>
          <span class="scope-note mono">字数 {{ content.length }}</span>
          <template #right>
            <n-button
              size="small"
              quaternary
              :disabled="submitting || content.length === 0"
              @click="clearContent"
            >
              清空内容
            </n-button>
          </template>
        </Toolbar>

        <p class="scope-hint" :class="{ 'scope-hint--warn': scope.isJoint.value }">{{ targetHint }}</p>

        <div class="textarea-wrap">
          <CommandHints
            v-if="showHints"
            :items="filteredCommands"
            :active-index="hintActive"
            @select="applyCommand"
          />
          <n-input
            v-model:value="content"
            type="textarea"
            :autosize="{ minRows: 8, maxRows: 22 }"
            placeholder="粘贴对话记录、搜索结果、文档片段或任意文本内容…（输入 ^ 可呼出指令候选）"
            @keydown="onCmdKeydown"
          />
        </div>

        <div class="cmd-hint">
          <p class="cmd-line">
            指令本身不落库（存储类指令除外，如
            <span class="ftag">^data</span> / <span class="ftag">^interaction</span> /
            <span class="ftag">^source</span> / <span class="ftag">^node</span> 会按其类型写入原文）。
          </p>
          <p class="cmd-line">
            AI 不可用时：纯存储与确定层指令（<span class="ftag">^merge</span>
            <span class="ftag">^delete</span> <span class="ftag">^node</span>
            <span class="ftag">^data</span> <span class="ftag">^help</span>）照常可用；语义层指令（<span
              class="ftag"
              >^compress</span
            >
            <span class="ftag">^update</span> <span class="ftag">^cmdmsg</span>）需要 AI，后端会返回原因。
          </p>
          <p class="cmd-line">
            只有 <span class="ftag">^英文动词</span> 一种形式是指令；其余写法（/ 前缀、中文词、冒号）一律按普通文本落库。
          </p>
        </div>
      </SectionCard>

      <!-- 三态：就绪（两块都不显示）/ 提交中 / 结果 -->
      <SectionCard v-if="submitting" title="提交结果">
        <StateBlock loading loading-text="提交中…" fixed-height />
      </SectionCard>

      <SectionCard v-else-if="result" title="提交结果">
        <div class="result" :class="`result--${result.kind}`">
          <p class="result-title">{{ result.title }}</p>
          <p v-if="result.detail" class="result-detail">{{ result.detail }}</p>
          <p v-if="result.error" class="result-error">{{ result.error }}</p>
          <div v-if="result.fields.length" class="result-fields">
            <div v-for="f in result.fields" :key="f.label" class="result-field">
              <span class="rf-label">{{ f.label }}</span>
              <span class="rf-value">{{ f.value }}</span>
            </div>
          </div>
        </div>
      </SectionCard>

      <!-- 处理历史（复用组件，其自带标题，故本卡片不再加标题以免重复） -->
      <SectionCard>
        <IngestHistory :items="history" @select="openEvent" />
      </SectionCard>
    </div>
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 信息传入（写入区，规约 §4.7）：手工贮存原文与发送指令。
 *
 * 硬要求：
 * - 目标书目默认跟随顶栏全局作用域；联查态下写入**活动书目**且必须显式说明写去哪本。
 * - **没有 auto 模式**：类型只能 interaction / data / source（后端对 auto 返回 422）。
 * - 降级可用（§5.5）：AI 不可用**不禁用提交**——纯存储与确定层指令照常成功，
 *   语义层指令的拒绝原因由后端原文透传显示（不静默）。
 * - 指令响应不进处理历史：清空输入 + 把 message 显示在结果区。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInput, NSelect, useMessage } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import CommandHints from '@/components/CommandHints.vue'
import IngestHistory from '@/components/IngestHistory.vue'
import * as eventsApi from '@/api/events'
import * as settingsApi from '@/api/settings'
import { ApiError } from '@/api/http'
import type { SettingsResponse } from '@/api/types'
import { commandToken, filterCommands } from '@/api/commands'
import type { CommandCandidate } from '@/api/commands'
import { usePolling } from '@/composables/usePolling'
import { useRepoScope } from '@/composables/useRepoScope'
import { useRepoWrite } from '@/composables/useRepoWrite'
import { useHealthStore } from '@/stores/health'
import { useSessionStore } from '@/stores/session'

const router = useRouter()
const message = useMessage()
const health = useHealthStore()
const session = useSessionStore()
const scope = useRepoScope()
const write = useRepoWrite()

/** 事件类型三选一（无 auto 模式：后端对 auto/缺省返回 422） */
const TYPE_OPTIONS = [
  { label: '交互 interaction（对话 / 决策记录）', value: 'interaction' },
  { label: '数据 data（事实资料 / 引用来源）', value: 'data' },
  { label: '来源 source（原始数据，仅存储不进图谱）', value: 'source' },
]

const content = ref('')
const eventType = ref('interaction')
const submitting = ref(false)

// ── 目标书目：跟随顶栏勾选的书目集合 ──
/** 恰好勾 1 本 → 该书目；勾了多本（联查）→ 空（后端缺省即活动书目） */
const writeRepoId = computed(() => scope.effectiveRepoId.value)
const targetName = computed(() =>
  scope.effectiveRepoId.value
    ? scope.repo.nameOf(scope.effectiveRepoId.value)
    : write.activeRepoName.value,
)
const targetHint = computed(() =>
  scope.isJoint.value
    ? `当前勾选了 ${scope.selectedIds.value.length} 本书目（联查 · 只读聚合）：写动作只作用于活动书目《${write.activeRepoName.value}》，不写进联查的其它库。要写别的书目请只勾选它。`
    : '目标书目由顶栏全局书目选择器决定；写入会把原文记进这本书目的时序事件存储（原文 · 仅人类可修订）。',
)

// ── AI 状态行（模型 / 地址 / 上次检查） ──
const settings = ref<SettingsResponse | null>(null)
/** 配置读取失败的后端原文（与 `settings === null` 的「没读到」同源；空串 = 没失败过） */
const settingsError = ref('')
const settingsLoading = ref(false)
const providerName = computed(() => settings.value?.active_provider || '—')
const modelName = computed(() => {
  const s = settings.value
  if (!s) return '—'
  if (s.active_model) return s.active_model
  const entry = s.providers?.[s.active_provider]
  const list = entry?.models ?? (entry?.model ? [entry.model] : [])
  return list[0] || '—'
})
const baseUrl = computed(() => {
  const s = settings.value
  if (!s) return ''
  return s.providers?.[s.active_provider]?.base_url || ''
})
const checkedText = computed(() =>
  health.checkedAt ? new Date(health.checkedAt).toLocaleTimeString('zh-CN') : '—',
)

async function loadSettings(): Promise<void> {
  settingsLoading.value = true
  try {
    settings.value = await settingsApi.getSettings()
    settingsError.value = ''
  } catch (e) {
    // 配置拿不到不影响写入，但**必须说出来**：否则 AI 状态行三项全「—」，
    // 与「根本没配 AI」同形，而上一行可能同时写着「AI 就绪」（用户无从判断）
    settingsError.value = (e as Error).message || String(e)
  } finally {
    settingsLoading.value = false
  }
}

// ── 指令候选（opencode 风格）：^ 触发 · 前缀过滤 · ↑↓/Enter/Tab/Esc ──
const hintsDismissed = ref(false)
const hintActive = ref(0)
const cmdToken = computed(() => commandToken(content.value))
const filteredCommands = computed(() =>
  cmdToken.value === null ? [] : filterCommands(cmdToken.value),
)
const showHints = computed(() => !hintsDismissed.value && filteredCommands.value.length > 0)

watch(content, () => {
  hintsDismissed.value = false
  hintActive.value = 0
})

function applyCommand(c: CommandCandidate): void {
  content.value = c.args ? `${c.name} ` : c.name
  hintsDismissed.value = true
}

function onCmdKeydown(e: KeyboardEvent): void {
  if (!showHints.value) return
  const list = filteredCommands.value
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    hintActive.value = (hintActive.value + 1) % list.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    hintActive.value = (hintActive.value - 1 + list.length) % list.length
  } else if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault()
    applyCommand(list[hintActive.value])
  } else if (e.key === 'Escape') {
    hintsDismissed.value = true
  }
}

function clearContent(): void {
  content.value = ''
}

// ── 提交结果（常驻可见，不只在 toast 里闪一下） ──
interface ResultField {
  label: string
  value: string
}
interface SubmitResult {
  kind: 'success' | 'command' | 'error'
  title: string
  detail: string
  /** 后端错误原文 */
  error: string
  fields: ResultField[]
}

const result = ref<SubmitResult | null>(null)

const STATUS_TEXT: Record<string, string> = {
  raw: '待处理（raw）',
  indexed: '已索引（indexed）',
  linked: '已入图（linked）',
  failed: '失败（failed）',
  skipped: '已跳过（skipped）',
}

// ── 提交 ──
async function submit(): Promise<void> {
  const text = content.value
  if (!text.trim()) {
    message.warning('内容不能为空')
    return
  }
  submitting.value = true
  result.value = null
  try {
    const res = await eventsApi.ingest(text, eventType.value, writeRepoId.value)

    if (res.command_triggered) {
      // 指令响应不进处理历史：清空输入 + 透传 message
      content.value = ''
      const msg = res.message || '指令已执行'
      const rejected = msg.includes('未执行') || msg.includes('未生效')
      result.value = {
        kind: 'command',
        title: rejected ? '指令未被接受（后端原文如下）' : '指令结果',
        detail: msg,
        error: '',
        fields: [
          { label: '指令触发', value: 'command_triggered = true' },
          { label: '事件', value: '指令本身不落库（存储类指令除外）' },
          { label: '目标书目', value: targetName.value },
        ],
      }
      if (rejected) message.warning('指令未执行，原因见结果区', { duration: 6000 })
      else message.success('指令已执行')
      await session.commit()
      await loadSettings()
      return
    }

    if (!res.event_id) {
      // 旧后端不认识该请求时 event_id 为空：明示而不是静默轮询 404
      result.value = {
        kind: 'error',
        title: '后端未返回事件 ID',
        detail: `status = ${res.status || '—'}，message = ${res.message || '—'}`,
        error: '后端版本可能过旧（不认识该写入请求），请重启后端服务后刷新页面。',
        fields: [],
      }
      message.warning('后端未返回事件 ID，请检查后端版本')
      return
    }

    const item: HistoryItem = {
      event_id: res.event_id,
      submitted_at: new Date().toISOString(),
      status: 'processing',
      repo_id: writeRepoId.value,
    }
    history.value.unshift(item)
    if (history.value.length > MAX_HISTORY) history.value.splice(MAX_HISTORY)
    pollAttempts.value[res.event_id] = 0
    persist()
    content.value = ''

    const fields: ResultField[] = [
      { label: '事件 ID', value: res.event_id },
      { label: '状态', value: STATUS_TEXT[res.status] || res.status },
      { label: '事件类型', value: eventType.value },
      { label: '写入书目', value: targetName.value },
      { label: '指令触发', value: 'command_triggered = false' },
    ]
    if (!health.aiAvailable) {
      fields.push({
        label: '降级提示',
        value: 'AI 未连接：原文已存入，模型恢复后自动补偿入图',
      })
    }
    result.value = {
      kind: 'success',
      title: '已写入原文',
      detail: res.message || 'Event ingested',
      error: '',
      fields,
    }
    if (health.aiAvailable) message.success('已提交，开始处理')
    else message.info('AI 未连接：原文已存入，等待恢复后自动补偿')
    await session.commit()
    await loadSettings()
    poll.tick()
  } catch (e) {
    // 失败路径：后端原文常驻结果区（不只在 toast 里）
    const err = e as Error
    const status = e instanceof ApiError ? `HTTP ${e.status}` : '请求失败'
    result.value = {
      kind: 'error',
      title: '提交失败（后端原文如下）',
      detail: status,
      error: err.message || String(e),
      fields: [
        { label: '目标书目', value: targetName.value },
        {
          label: '提示',
          value: health.aiAvailable
            ? '语义层指令在 AI 就绪时才可用；纯存储写入不受影响。'
            : 'AI 不可用时：纯存储与确定层指令（^merge / ^delete / ^node / ^data / ^help）照常可用。',
        },
      ],
    }
    message.error(err.message || '提交失败')
  } finally {
    submitting.value = false
  }
}

// ── 处理历史（localStorage 常驻 + 状态轮询） ──
interface HistoryItem {
  event_id: string
  submitted_at: string
  status: string
  node_count?: number
  /** 提交时的目标书目（跨书目轮询/跳转要用） */
  repo_id?: string
  /** 连续读取失败次数（非 404）：让「处理中…」不再是一个永不说真话的状态 */
  read_failures?: number
}

const STORAGE_KEY = 'dpim_ingest_history'
const MAX_HISTORY = 10
/** 本地模型单事件最多约 8 次 LLM 调用，轮询窗口放宽（避免被误标超时） */
const MAX_POLL_ATTEMPTS = 1080

const history = ref<HistoryItem[]>([])
const pollAttempts = ref<Record<string, number>>({})

const TERMINAL = new Set(['linked', 'failed', 'skipped', 'timeout', 'removed'])

function persist(): void {
  const slim = history.value.map((h) => ({
    event_id: h.event_id,
    submitted_at: h.submitted_at,
    repo_id: h.repo_id ?? '',
  }))
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(slim))
  } catch {
    /* 存储配额/隐私模式：忽略 */
  }
}

function restore(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw) as Array<{
      event_id: string
      submitted_at: string
      repo_id?: string
    }>
    if (!Array.isArray(parsed)) return
    history.value = parsed.map((h) => ({
      event_id: h.event_id,
      submitted_at: h.submitted_at,
      repo_id: h.repo_id || '',
      status: 'processing',
    }))
    pollAttempts.value = {}
  } catch {
    /* 解析失败忽略 */
  }
}

async function refreshPending(): Promise<void> {
  let changed = false
  for (const item of history.value) {
    if (TERMINAL.has(item.status)) continue
    const attempts = pollAttempts.value[item.event_id] ?? 0
    if (attempts >= MAX_POLL_ATTEMPTS) {
      item.status = 'timeout'
      changed = true
      continue
    }
    pollAttempts.value[item.event_id] = attempts + 1
    try {
      // 跨书目读取必须带书目参数，否则只在活动书目里找（静默 404）
      const ev = await eventsApi.getEvent(item.event_id, item.repo_id || undefined)
      item.read_failures = 0
      if (ev.status === 'linked') {
        item.status = 'linked'
        item.node_count = Array.isArray(ev.graph_refs) ? ev.graph_refs.length : 0
        changed = true
      } else if (ev.status === 'failed' || ev.status === 'skipped') {
        item.status = ev.status
        changed = true
      } else {
        item.status = 'indexed'
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // 事件已被删除（人删的、或换库后不在这个库里）：终态，不再轮询——
        // 旧状是空 catch 吞掉，这一行会一直停在「处理中…」直到 1080 次后超时
        item.status = 'removed'
        changed = true
      } else {
        // 网络抖动 / 5xx / 401：累计次数并**显示出来**（不静默），状态保持「处理中」继续轮询。
        // 不必 persist：失败次数是内存态（localStorage 只存 id / 时间 / 书目），
        // 靠响应式即可让那一行立刻变成「状态未知（N 次读取失败）」。
        item.read_failures = (item.read_failures ?? 0) + 1
      }
    }
  }
  if (changed) persist()
}

const poll = usePolling(refreshPending, 5000)

function openEvent(eventId: string): void {
  void router.push({ name: 'events', query: { event: eventId } })
}

onMounted(() => {
  restore()
  void loadSettings()
  poll.start()
})
</script>

<style scoped>
.ingest-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
}
.ingest-scroll > * {
  flex-shrink: 0;
}
.rows {
  display: flex;
  flex-direction: column;
}
.row-item {
  display: flex;
  align-items: baseline;
  gap: var(--dpim-space-4);
  padding: var(--dpim-space-2) 0;
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
}
.row-item:last-child {
  border-bottom: none;
}
.row-label {
  width: 96px;
  flex-shrink: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.row-value {
  min-width: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
  word-break: break-all;
}
.row-value.mono {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
}
.row-value.ok {
  color: var(--dpim-success);
}
.row-value.warn {
  color: var(--dpim-warning);
}
.row-value.bad {
  color: var(--dpim-danger);
}
.f-type {
  width: 240px;
}
.scope-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  white-space: nowrap;
}
.mono {
  font-family: var(--dpim-font-mono);
}
.scope-hint {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.6;
}
/* 联查态：这是一条写动作警告，不只是提示（口径与 StorageCheckPage 的 warn-note 一致） */
.scope-hint--warn {
  color: var(--dpim-warning);
}
.textarea-wrap {
  position: relative;
}
.cmd-hint {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
}
.cmd-line {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.7;
}
.ftag {
  color: var(--dpim-primary);
  font-family: var(--dpim-font-mono);
}
.result {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-3);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
  background: var(--dpim-inset);
  box-shadow: var(--dpim-inset-shadow);
}
.result--success {
  border-color: var(--dpim-success);
  background: var(--dpim-success-soft);
}
.result--command {
  border-color: var(--dpim-primary-border);
  background: var(--dpim-primary-soft);
}
.result--error {
  border-color: var(--dpim-danger);
  background: var(--dpim-danger-soft);
}
.result-title {
  margin: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
}
.result-detail {
  margin: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text-2);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.result-error {
  margin: 0;
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-danger);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.result-fields {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
}
.result-field {
  display: flex;
  align-items: baseline;
  gap: var(--dpim-space-3);
  font-size: var(--dpim-fs-sm);
}
.rf-label {
  width: 96px;
  flex-shrink: 0;
  color: var(--dpim-text-3);
}
.rf-value {
  min-width: 0;
  color: var(--dpim-text);
  word-break: break-all;
}
</style>
