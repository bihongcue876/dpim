<template>
  <PageShell
    zone="观测"
    title="日志"
    description="本地翻看前后端运行日志：按天轮转、只读尾部，不经过任何 AI 通道"
  >
    <template #actions>
      <n-button type="primary" size="small" :loading="running" @click="reload">刷新</n-button>
    </template>

    <Toolbar>
      <n-radio-group
        :value="kind"
        :disabled="running"
        size="small"
        @update:value="onKindChange"
      >
        <n-radio-button value="backend">后端日志</n-radio-button>
        <n-radio-button value="frontend">前端日志</n-radio-button>
      </n-radio-group>

      <n-select
        v-model:value="date"
        size="small"
        class="f-select"
        :options="dateOptions"
        :disabled="running"
        placeholder="日期（最新）"
        clearable
        @update:value="reload"
      />
      <n-select
        v-model:value="level"
        size="small"
        class="f-select-narrow"
        :options="LEVEL_OPTIONS"
        :disabled="running"
        placeholder="级别"
        clearable
        @update:value="reload"
      />
      <n-input
        v-model:value="keyword"
        size="small"
        class="f-input"
        :disabled="running"
        placeholder="关键词（不区分大小写）"
        clearable
        @keyup.enter="reload"
      />
      <n-select
        v-model:value="tail"
        size="small"
        class="f-select-narrow"
        :options="TAIL_OPTIONS"
        :disabled="running"
        @update:value="reload"
      />
      <n-button size="small" :loading="running" @click="reload">查询</n-button>
      <n-button size="small" quaternary :disabled="running" @click="resetAll">重置</n-button>

      <template #right>
        <span class="note">{{ kindLabel }} · {{ shownDate }} · 尾部 {{ tail }} 行</span>
      </template>
    </Toolbar>

    <!-- 日志正文自带内部滚动（flex:1 + min-height:0 逐层传递），不把整页撑爆 -->
    <SectionCard :title="kindLabel" :hint="cardHint" flush class="log-card">
      <template #actions>
        <span v-if="dir" class="dir-path" :title="`日志目录：${dir}`">{{ dir }}</span>
      </template>

      <!-- 三态互斥：加载 / 失败（显示后端错误原文 + 日志目录）/ 空 -->
      <StateBlock v-if="showLoading" loading loading-text="正在读取日志…" />

      <StateBlock v-else-if="error" :error="error">
        <template #retry>
          <p class="dir-line">
            日志目录：
            <span v-if="dir" class="dir-path dir-path--inline">{{ dir }}</span>
            <span v-else class="dir-unknown">未能取得（读取失败）——默认在 DPIM 数据目录下的 logs/</span>
          </p>
          <p class="dir-line">可用文件管理器直接打开该目录查看原始文件；本页只读，不会改动日志。</p>
          <n-button size="small" @click="reload">重试</n-button>
        </template>
      </StateBlock>

      <StateBlock v-else-if="lines.length === 0" :empty-text="emptyText" :hint="emptyHint">
        <template #extra>
          <p v-if="dir" class="dir-line">
            日志目录：<span class="dir-path dir-path--inline">{{ dir }}</span>
          </p>
        </template>
      </StateBlock>

      <!-- 等宽 + 可滚动：行超长时折行，整页不被撑爆（滚的是这个 pre，不是页面） -->
      <pre v-else class="log-body"><span v-for="(line, i) in lines" :key="i" class="log-line" :class="levelClass(line)">{{ line }}</span></pre>
    </SectionCard>
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 日志（观测区）：本地翻看前后端日志文件——P1 可见性的最底层兜底。
 *
 * 数据面只有 `GET /logs`（经 `api/logs.ts`）：**不做服务端分页**，
 * `tail` 就是它的分页语义（只读尾部 N 行，`truncated` 表示过滤后仍多于此）。
 * 本页不主动上报前端日志（上报走 `reportClientLog`，由失败路径统一收口）；
 * 但读取失败时必须把后端错误原文与日志目录**显示在页面上**，不能只在 toast 里闪一下。
 */
import { computed, ref } from 'vue'
import { NButton, NInput, NRadioButton, NRadioGroup, NSelect } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import * as logsApi from '@/api/logs'
import { useAsyncAction } from '@/composables/useAsyncAction'

const LEVEL_OPTIONS = [
  { label: 'debug', value: 'debug' },
  { label: 'info', value: 'info' },
  { label: 'warning', value: 'warning' },
  { label: 'error', value: 'error' },
]

/** 尾部行数三档（tail 即日志的分页语义） */
const TAIL_OPTIONS = [
  { label: '尾部 200 行', value: 200 },
  { label: '尾部 500 行', value: 500 },
  { label: '尾部 1000 行', value: 1000 },
]

const kind = ref('backend')
const date = ref<string | null>(null)
const level = ref<string | null>(null)
const keyword = ref('')
const tail = ref(200)

const { running, error, lastResult, run } = useAsyncAction(() =>
  logsApi.listLogs({
    kind: kind.value,
    date: date.value || undefined,
    level: level.value || undefined,
    keyword: keyword.value.trim() || undefined,
    tail: tail.value,
  }),
)

/** 当前筛选的指纹：与「已加载指纹」不一致时显示加载态，避免串通道显示旧行 */
const queryKey = computed(() =>
  [kind.value, date.value ?? '', level.value ?? '', keyword.value.trim(), tail.value].join('\u0000'),
)
const loadedKey = ref('')

const result = computed(() => lastResult.value)
const dir = computed(() => result.value?.dir ?? '')
const lines = computed(() => result.value?.lines ?? [])
const files = computed(() => result.value?.files ?? [])

const kindLabel = computed(() => (kind.value === 'frontend' ? '前端日志' : '后端日志'))
const shownDate = computed(() => date.value || result.value?.date || '最新')
const showLoading = computed(() => running.value && loadedKey.value !== queryKey.value)

const currentFile = computed(() =>
  files.value.find((f) => f.date === (result.value?.date ?? '')),
)

const dateOptions = computed(() =>
  files.value.map((f) => ({ label: `${f.date} · ${bytes(f.size)}`, value: f.date })),
)

const cardHint = computed(() => {
  if (!result.value) return '按天轮转，后端保留最近若干天；本页只读尾部，不写任何状态。'
  const parts = [
    result.value.truncated
      ? `已截断：仅显示最新 ${lines.value.length} 行`
      : `显示 ${lines.value.length} 行`,
    `日期 ${result.value.date || '—'}`,
  ]
  if (currentFile.value) parts.push(`文件 ${currentFile.value.name}（${bytes(currentFile.value.size)}）`)
  if (result.value.truncated) {
    parts.push('匹配行多于所选尾部档位，可加关键词或选更大档位')
  }
  return parts.join(' · ')
})

const emptyText = computed(() =>
  files.value.length === 0 ? `没有${kindLabel.value}文件` : '当前筛选没有匹配的日志行',
)

const emptyHint = computed(() =>
  files.value.length === 0
    ? '后端启动后才会写入日志文件（按天轮转）；前端日志由浏览器失败上报写入。'
    : '可放宽级别 / 关键词，或换一天再查。',
)

async function reload(): Promise<void> {
  const res = await run()
  if (!res) {
    loadedKey.value = ''
    return
  }
  // 未指定日期时，把下拉对齐到实际返回的那一天（可清除回「最新」）
  if (!date.value && res.date) date.value = res.date
  loadedKey.value = queryKey.value
}

/** 切换通道：旧日期在另一通道可能不存在，回到「最新」并强制显示加载态 */
function onKindChange(value: unknown): void {
  kind.value = value === 'frontend' ? 'frontend' : 'backend'
  date.value = null
  loadedKey.value = ''
  void reload()
}

function resetAll(): void {
  kind.value = 'backend'
  date.value = null
  level.value = null
  keyword.value = ''
  tail.value = 200
  loadedKey.value = ''
  void reload()
}

/** 行内级别着色（只读取行内 `| LEVEL` 标记，仅用于肉眼定位） */
function levelClass(line: string): string {
  const upper = line.toUpperCase()
  if (upper.includes('| ERROR')) return 'log-line--error'
  if (upper.includes('| WARNING')) return 'log-line--warning'
  if (upper.includes('| DEBUG')) return 'log-line--debug'
  return ''
}

function bytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(2)} MiB`
}

// 进页即取一次（日志是只读端点，不需要状态密钥或确认）
void reload()
</script>

<style scoped>
.log-card {
  flex: 1;
  min-height: 0;
}
.f-select {
  width: 24ch;
}
.f-select-narrow {
  width: 18ch;
}
.f-input {
  width: 32ch;
}
.note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  white-space: nowrap;
}
.dir-path {
  display: inline-block;
  max-width: 46ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  user-select: all;
}
.dir-path--inline {
  max-width: none;
  white-space: normal;
  word-break: break-all;
  color: var(--dpim-text-2);
}
.dir-line {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.5;
}
.dir-unknown {
  color: var(--dpim-text-2);
}
.log-body {
  flex: 1;
  min-height: 0;
  margin: 0;
  overflow: auto;
  padding: var(--dpim-space-2) 0;
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.log-line {
  display: block;
  padding: 0 var(--dpim-space-3);
  color: var(--dpim-text-2);
}
.log-line--error {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.log-line--warning {
  background: var(--dpim-warning-soft);
  color: var(--dpim-warning);
}
.log-line--debug {
  color: var(--dpim-text-3);
}
</style>
