<template>
  <PageShell
    zone="观测"
    title="概览台"
    description="一眼看清这座图书馆现在怎么样"
  >
    <template #actions>
      <n-button type="primary" size="small" :loading="health.loading" @click="refreshAll">
        刷新
      </n-button>
    </template>

    <!-- P6：后端不可达时整页降级为「连接不上 + 地址 + 重试」，不留空白 -->
    <StateBlock
      v-if="!health.connected && health.error"
      :error="`连接不上后端：${backendLabel}`"
      empty-text=""
    >
      <template #retry>
        <div class="offline">
          <p class="offline-detail">{{ health.error }}</p>
          <n-button size="small" @click="refreshAll">重试</n-button>
        </div>
      </template>
    </StateBlock>

    <div v-else class="overview-scroll">
      <SectionCard title="图书馆" hint="书目 = 一本书（一 memory.db + 一 graph.json）；分组 = 书架">
        <div class="tiles">
          <StatTile
            :label="isJoint ? '当前作用域（联查）' : '当前书目'"
            :value="isJoint ? `勾选 ${selectedIds.length} 本` : (repo.activeRepo?.name ?? '—')"
            :hint="scopeHint"
            tone="primary"
            wide
          />
          <StatTile label="书目总数" :value="repo.repos.length" unit="本" />
          <StatTile
            label="受管 · 已加载"
            :value="repo.usableRepos.length"
            unit="本"
            :hint="`休眠/未加载 ${repo.repos.length - repo.usableRepos.length} 本`"
          />
          <StatTile label="后端版本" :value="health.version" />
        </div>
      </SectionCard>

      <SectionCard
        title="双区统计"
        :hint="
          isJoint
            ? '线层 = 原文（仅人类可修订）；图层 = 衍生知识（可由 AI 维护）。联查态的总数为**勾选书目的逐库合计**'
            : '线层 = 原文（仅人类可修订）；图层 = 衍生知识（可由 AI 维护）'
        "
      >
        <p v-if="isJoint" class="warn-note">
          `/health` 的 raw / indexed / linked / failed / skipped 明细**只有活动书目口径**（后端没有按库参数）：
          联查态下这四项显示「—」，活动书目的值写在提示里，绝不拿一本的数冒充勾选集合的合计。
        </p>
        <div class="tiles">
          <StatTile label="事件总数（原文）" :value="num(eventLine.total_events)" />
          <StatTile label="知识节点（衍生）" :value="num(graphLayer.total_nodes)" />
          <StatTile
            label="已入图事件"
            :value="isJoint ? '—' : num(eventLine.linked)"
            :hint="isJoint ? activeOnlyHint(health.eventLine.linked) : ''"
            tone="success"
          />
          <StatTile
            label="失败事件"
            :value="isJoint ? '—' : num(eventLine.failed)"
            :hint="isJoint ? activeOnlyHint(health.eventLine.failed) : ''"
            :tone="!isJoint && (eventLine.failed ?? 0) > 0 ? 'danger' : 'default'"
          />
          <StatTile
            label="待处理（raw）"
            :value="isJoint ? '—' : num(eventLine.raw)"
            :hint="isJoint ? activeOnlyHint(health.eventLine.raw) : ''"
          />
          <StatTile
            label="已跳过（skipped）"
            :value="isJoint ? '—' : num(eventLine.skipped)"
            :hint="isJoint ? activeOnlyHint(health.eventLine.skipped) : ''"
          />
        </div>
        <div v-if="isJoint" class="rows">
          <p class="note">逐库明细（勾选的每一本各一行，数字来自 `GET /repos` 的实时计数）：</p>
          <div v-for="row in jointRows" :key="row.repo_id" class="row-item">
            <span class="row-label">{{ row.name }}</span>
            <span class="row-value mono">
              原文 {{ num(row.total_events) }} · 节点 {{ num(row.total_nodes) }}
              <template v-if="row.load_error">· 未加载：{{ row.load_error }}</template>
            </span>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="容量与保障"
        :hint="
          isJoint
            ? '联查态：容量/备份/操作日志的逐库值请在「存储体检」页按勾选集合跑一次校验（sizes/counts 会逐库汇总）'
            : '存储层的体量与退路必须看得见'
        "
      >
        <div class="tiles">
          <StatTile
            label="主库体积"
            :value="isJoint ? '—' : bytes(storage?.db_bytes)"
            :hint="isJoint ? activeOnlyHint(storage?.db_bytes) : ''"
          />
          <StatTile
            label="WAL 体积"
            :value="isJoint ? '—' : bytes(storage?.wal_bytes)"
            :hint="isJoint ? activeOnlyHint(storage?.wal_bytes) : ''"
          />
          <StatTile
            label="图层文件"
            :value="isJoint ? '—' : bytes(storage?.json_bytes)"
            :hint="isJoint ? activeOnlyHint(storage?.json_bytes) : ''"
          />
          <StatTile
            label="备份份数"
            :value="isJoint ? '—' : (storage?.backups ?? '—')"
            :hint="isJoint ? activeOnlyHint(storage?.backups) : ''"
            :tone="!isJoint && (storage?.backups ?? 0) > 0 ? 'success' : 'warning'"
          />
          <StatTile
            label="图层操作日志"
            :value="isJoint ? '—' : (storage?.graph_ops ?? '—')"
            :hint="isJoint ? activeOnlyHint(storage?.graph_ops) : ''"
            unit="条"
          />
          <StatTile
            label="队列深度"
            :value="health.queueDepth"
            :hint="health.workerRunning ? 'worker 运行中（全后端共一个队列）' : 'worker 未运行'"
            :tone="health.queueDepth > 0 ? 'warning' : 'default'"
          />
        </div>
      </SectionCard>

      <SectionCard title="运行状态">
        <div class="rows">
          <div class="row-item">
            <span class="row-label">连接</span>
            <span class="row-value" :class="health.connected ? 'ok' : 'bad'">
              {{ health.connected ? '已连接' : '未连接' }}
            </span>
          </div>
          <div class="row-item">
            <span class="row-label">AI 管线</span>
            <span class="row-value" :class="health.aiStatus === 'ready' ? 'ok' : 'warn'">
              {{ health.aiStatusText }}
            </span>
          </div>
          <div v-if="health.aiReason" class="row-item">
            <span class="row-label">AI 原因</span>
            <span class="row-value warn">{{ health.aiReason }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">书目作用域</span>
            <span class="row-value">{{ scope.scopeLabel.value }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">最近事件</span>
            <span class="row-value">{{ health.lastEventAt || '—' }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">状态校验密钥</span>
            <!-- 读取失败必须说出来：旧状是继续显示旧值 / 「—」，用户无从知道密钥没刷新（写后一致性判据失效） -->
            <template v-if="session.error">
              <span class="row-value bad">读取失败：{{ session.error }}</span>
              <n-button size="tiny" :loading="session.loading" @click="retrySession">重试</n-button>
            </template>
            <span v-else class="row-value mono">{{ session.stateKey || '—' }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">上次检查</span>
            <span class="row-value">{{ checkedText }}</span>
          </div>
        </div>
      </SectionCard>
    </div>
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 概览台（观测区）：图书馆现状一屏可见。
 *
 * P1 可见性：容量 / 备份份数 / WAL / 队列 / 降级原因 / 状态密钥全部有落脚处，
 * 不再依赖「只在日志里」或「只在某一页可见」。
 *
 * 书目作用域（勾选集合）：**`GET /health` 后端没有 `repo_id` 参数**（`interface/routers/settings.py`
 * 的 `health()` 只报活动书目），所以联查态能按勾选集合取到的只有 `GET /repos` 的**逐库实时计数**
 * （事件/节点），这两项做逐库合计；raw/linked/failed/skipped 与容量/备份只有活动书目口径，
 * 一律显示「—」并把活动书目的值写进提示——绝不拿一本的数冒充勾选集合的合计。
 * 逐库的体积与一致性结论在「存储体检」页按勾选集合跑校验（那里逐库汇总）。
 */
import { computed } from 'vue'
import { NButton } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import StatTile from '@/components/ui/StatTile.vue'
import { backendBase } from '@/api/http'
import { useRepoScope } from '@/composables/useRepoScope'
import { useHealthStore } from '@/stores/health'
import { useRepoStore } from '@/stores/repo'
import { useSessionStore } from '@/stores/session'

const health = useHealthStore()
const repo = useRepoStore()
const session = useSessionStore()
const scope = useRepoScope()

const { isJoint, selectedIds, selectedRepos } = scope

const activeRepoName = computed(() => repo.activeRepo?.name ?? '—')

/** 逐库求和（`GET /repos` 的计数：休眠/未加载的库是 null，不参与、也不当成 0） */
function sumOf(pick: (r: (typeof selectedRepos.value)[number]) => number | null): number | undefined {
  const numbers = selectedRepos.value
    .map(pick)
    .filter((v): v is number => typeof v === 'number')
  if (!numbers.length) return undefined
  return numbers.reduce((a, b) => a + b, 0)
}

/**
 * 双区统计：单库作用域 = /health 的当前值；
 * 联查 = 只有「逐库可得的计数」做合计，状态明细留空（见上方口径说明）。
 */
const eventLine = computed(() =>
  isJoint.value ? { total_events: sumOf((r) => r.total_events) } : health.eventLine,
)
const graphLayer = computed(() =>
  isJoint.value ? { total_nodes: sumOf((r) => r.total_nodes) } : health.graphLayer,
)

/** 容量与保障：只有活动书目口径（/health 没有按库参数），联查态一律显示「—」 */
const storage = computed(() => health.storage)

/** 逐库明细（联查态的合计必须能看出是怎么来的） */
const jointRows = computed(() =>
  selectedRepos.value.map((r) => ({
    repo_id: r.repo_id,
    name: r.name,
    total_events: r.total_events,
    total_nodes: r.total_nodes,
    load_error: r.load_error ?? '',
  })),
)

/** 联查态：这些数字只有活动书目口径 → 值显示「—」，把活动书目的值写进提示（不冒充合计） */
function activeOnlyHint(value: number | undefined): string {
  return `联查不适用（/health 只报活动书目《${activeRepoName.value}》：${value ?? '—'}）`
}

const scopeHint = computed(() =>
  isJoint.value
    ? `${scope.scopeLabel.value}（合计与逐库明细见下表）`
    : repo.activeRepo
      ? `书架 · ${repo.activeRepo.group || '未分组'}`
      : '尚无活动书目',
)

/** 后端地址标签：未配置时显示同源地址（P6：离线时要告诉用户它在找哪里） */
const backendLabel = computed(() => backendBase() || window.location.origin)

const checkedText = computed(() =>
  health.checkedAt ? new Date(health.checkedAt).toLocaleTimeString('zh-CN') : '—',
)

function num(value: number | null | undefined): string {
  return value === undefined || value === null ? '—' : String(value)
}

function bytes(value: number | undefined): string {
  if (value === undefined || value === null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(2)} MiB`
}

async function refreshAll(): Promise<void> {
  await Promise.all([repo.load(), health.refresh(), session.validate().catch(() => undefined)])
}

/** 状态校验密钥的重试：失败原因由 store 收着，这里只负责把原文常驻显示出来（不抛） */
async function retrySession(): Promise<void> {
  try {
    await session.validate()
  } catch {
    /* 失败原文在 session.error，上面那一行会显示 */
  }
}
</script>

<style scoped>
.overview-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
}
/* SectionCard 自带 overflow:hidden → 其自动最小高度为 0，在列向 flex 里会被压扁裁掉
   而不是让外层滚动。所有直接子项必须 flex-shrink:0（StorageCheckPage 同类修正）。 */
.overview-scroll > * {
  flex-shrink: 0;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--dpim-space-2);
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
  width: 120px;
  flex-shrink: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.5;
}
/* 联查态的口径警告（口径与 StorageCheckPage 的 warn-note 一致） */
.warn-note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-warning);
  line-height: 1.5;
}
.row-value {
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
.row-value.bad {
  color: var(--dpim-danger);
}
.row-value.warn {
  color: var(--dpim-warning);
}
.offline {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--dpim-space-2);
}
.offline-detail {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  max-width: 60ch;
  word-break: break-word;
}
</style>
