<template>
  <PageShell
    zone="观测"
    title="存储体检"
    description="可行性测试：一致性校验、容量与计数、图层操作日志、WAL 与书目修复"
  >
    <template #actions>
      <n-button type="primary" size="small" :loading="verifyRunning" @click="runVerify">
        运行校验
      </n-button>
    </template>

    <Toolbar>
      <span class="note">作用域：{{ scopeLabel }}</span>
      <span v-if="isJoint" class="warn-note">
        联查（勾选 {{ selectedIds.length }} 本）：校验与操作日志按勾选集合**逐库**汇总；
        维护动作（WAL 检查点 / 刷新修复）是写动作，只作用于活动书目《{{ writeRepoName }}》。
      </span>
      <template #right>
        <n-button size="small" quaternary :loading="opsLoading" @click="reloadAll">刷新</n-button>
      </template>
    </Toolbar>

    <div class="sc-scroll">
      <!-- ① 校验结论 + 校验项表格 -->
      <SectionCard title="一致性校验" :hint="verifyHint">
        <template #actions>
          <span v-if="hasVerifyResult" class="note">
            {{ failedChecks.length }} 项未通过 / 共 {{ checks.length }} 项
          </span>
        </template>

        <!-- 三态互斥：运行中 / 失败（错误原文常驻）/ 未运行（引导）/ 结果 -->
        <StateBlock
          v-if="verifyRunning && !hasVerifyResult"
          loading
          loading-text="正在校验存储层（完整性 / 索引 / 操作日志重放 / 源证）…"
          fixed-height
        />
        <StateBlock v-else-if="verifyError && !hasVerifyResult" :error="verifyError" fixed-height>
          <template #retry>
            <p class="note">校验接口失败：错误原文见上（不做静默降级，也不重试掩盖）。</p>
            <n-button size="small" @click="runVerify">重试</n-button>
          </template>
        </StateBlock>
        <StateBlock
          v-else-if="!hasVerifyResult"
          empty-text="尚未运行校验"
          hint="点上方「运行校验」开始：SQLite 完整性 / 外键 / events↔events_fts / 节点↔node_fts / 操作日志重放一致性 / 悬空源证 / 缺 data 节点 / 图层文件无悬空边。只读，不改动任何数据；勾选多本时逐库各跑一遍。"
          fixed-height
        />

        <template v-else>
          <p v-if="verifyError" class="fail-reason">
            部分书目校验失败（这些库没有结论，不是「通过」）：{{ verifyError }}
          </p>
          <div class="verdict" :class="verifyOk ? 'verdict--ok' : 'verdict--bad'">
            <span class="verdict-mark">{{ verifyOk ? 'OK' : 'FAIL' }}</span>
            <span class="verdict-text">
              {{
                verifyOk
                  ? `全部 ${checks.length} 项通过：存储层当前可信任${runCount > 1 ? `（逐库跑了 ${runCount} 本）` : ''}`
                  : `${failedChecks.length} / ${checks.length} 项未通过${runCount > 1 ? `（逐库跑了 ${runCount} 本）` : ''}——下表已高亮，细节与错误原文均在「细节」列`
              }}
            </span>
          </div>

          <DataTable
            :columns="checkColumns"
            :rows="checks"
            row-key="row_key"
            empty-text="校验未返回任何检查项"
            empty-hint="接口返回的 checks 为空，可能是后端版本不匹配。"
          >
            <template #cell-repo_name="{ row }">
              <span class="check-key">{{ row.repo_name }}</span>
            </template>
            <template #cell-name="{ row }">
              <span class="check-name">
                <span :class="row.ok ? 'check-label' : 'check-label check-label--fail'">
                  {{ checkLabel(row.name) }}
                </span>
                <span class="check-key">{{ row.name }}</span>
              </span>
            </template>
            <template #cell-ok="{ row }">
              <span class="check-badge" :class="row.ok ? 'check-badge--ok' : 'check-badge--fail'">
                {{ row.ok ? 'OK' : 'FAIL' }}
              </span>
            </template>
            <template #cell-detail="{ row }">
              <span :class="row.ok ? 'check-detail' : 'check-detail check-detail--fail'">
                {{ row.detail || '—' }}
              </span>
            </template>
          </DataTable>
        </template>
      </SectionCard>

      <!-- ② 容量与计数 -->
      <SectionCard title="容量与计数" :hint="capacityHint">
        <div class="tiles">
          <StatTile
            v-for="tile in tiles"
            :key="tile.label"
            :label="tile.label"
            :value="tile.value"
            :unit="tile.unit"
            :hint="tile.hint"
            :tone="tile.tone"
          />
        </div>
        <div v-if="extraRows.length" class="result-rows">
          <p class="note">本次校验返回的其余项（非数字一律按 JSON 安全展示）：</p>
          <div v-for="item in extraRows" :key="item.key" class="row-item">
            <span class="row-label mono">{{ item.key }}</span>
            <span class="row-value">{{ item.value }}</span>
          </div>
        </div>
      </SectionCard>

      <!-- ③ 图层操作日志（审计：谁 / 何时 / 因何改了图） -->
      <SectionCard
        title="图层操作日志"
        hint="衍生知识（图层）的改动审计：节点/边的写入与删除都落一条；被删除节点的原数据就在 payload 里，可追溯可重放"
        class="ops-card"
      >
        <template #actions>
          <span class="note">共 {{ opTotal }} 条</span>
        </template>

        <DataTable
          :columns="opColumns"
          :rows="opItems"
          row-key="row_id"
          :loading="opsLoading"
          :error="opsError"
          :selected-key="selectedOpKey"
          empty-text="该书目还没有图层操作记录"
          empty-hint="图层的节点/边写入、删除、清空都会落一条操作日志（重放与审计的依据）。"
          :total="opTotal"
          :page-size="opPageSize"
          :offset="opOffset"
          @row-click="onOpClick"
          @update:offset="opSetOffset"
        >
          <template #cell-created_at="{ row }">
            <span class="mono">{{ shortTime(row.created_at) }}</span>
          </template>
          <template #cell-repo_name="{ row }">
            <span class="check-key">{{ row.repo_name }}</span>
          </template>
          <template #cell-op_kind="{ row }">
            <span class="tag" :class="`tag--${row.op_kind}`">{{ opKindText(row.op_kind) }}</span>
          </template>
          <template #cell-actor="{ row }">
            <span class="mono">{{ row.actor || '—' }}</span>
          </template>
          <template #cell-reason="{ row }">
            <span class="clamp">{{ row.reason || '—' }}</span>
          </template>
          <template #cell-payload="{ row }">
            <span class="payload-brief">{{ payloadText(row.payload) }}</span>
          </template>
        </DataTable>

        <div v-if="selectedOp" class="payload-box">
          <div class="payload-head">
            <span class="payload-title">
              payload 全文 · op #{{ selectedOp.op_id }} · {{ opKindText(selectedOp.op_kind) }} ·
              {{ selectedOp.repo_name }}
            </span>
            <n-button size="tiny" quaternary @click="selectedOp = null">收起</n-button>
          </div>
          <pre class="payload-json">{{ payloadPretty(selectedOp.payload) }}</pre>
        </div>
        <p v-else class="note">
          点选一行展开 payload 全文：节点删除的原数据（title / content / 源证）就在这里，是「谁 / 何时 / 因何改了图」的凭据。
        </p>
      </SectionCard>

      <!-- ④ WAL 检查点 + ⑤ 刷新修复书目 -->
      <SectionCard
        title="维护动作"
        hint="两者都是显式写操作，目标是活动书目；单库作用域下就是正在查看的那一本"
      >
        <p v-if="isJoint" class="warn-note">
          联查（勾选 {{ selectedIds.length }} 本）：下面两个写动作只作用于活动书目《{{
            writeRepoName
          }}》，不会作用到联查的其它库。
        </p>
        <div class="act-row">
          <div class="act-text">
            <p class="act-title">WAL 检查点</p>
            <p class="act-desc">
              收回主库并截断 WAL，防长期运行无界增长。空闲时立即完成；有并发写入时 busy 会大于 0，稍后再执行即可。
            </p>
          </div>
          <n-button size="small" :loading="ckptRunning" @click="ckptOpen = true">
            执行检查点
          </n-button>
        </div>
        <div v-if="ckptResult" class="result-rows">
          <div class="row-item">
            <span class="row-label">busy</span>
            <span class="row-value mono">{{ ckptResult.busy }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">log_frames（WAL 内帧数）</span>
            <span class="row-value mono">{{ ckptResult.log_frames }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">checkpointed_frames（已收回）</span>
            <span class="row-value mono">{{ ckptResult.checkpointed_frames }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">wal_bytes（截断后）</span>
            <span class="row-value mono">{{ bytes(ckptResult.wal_bytes) }}</span>
          </div>
        </div>
        <p v-else-if="ckptError" class="fail-reason">检查点失败：{{ ckptError }}</p>

        <div class="act-row">
          <div class="act-text">
            <p class="act-title">刷新修复书目</p>
            <p class="act-desc">
              重载该库（坏文件走留档，不静默覆盖）：重新读取 db 与图层文件，必要时按操作日志重建图层，并回报节点/边与对账变化。
            </p>
          </div>
          <n-button
            size="small"
            :loading="refreshRunning"
            :disabled="!canRefreshRepo"
            @click="doRefreshRepo"
          >
            刷新修复{{ canRefreshRepo ? `《${writeRepoName}》` : '' }}
          </n-button>
        </div>
        <p v-if="!canRefreshRepo" class="note">
          当前没有可用的书目（活动书目未加载）：无法确定要重载哪一本。
        </p>
        <div v-if="refreshResult" class="result-rows">
          <div class="row-item">
            <span class="row-label">结果</span>
            <span class="row-value">{{ refreshResult.message || '已重载' }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">书目</span>
            <span class="row-value">{{ refreshResult.name }}（{{ refreshResult.repo_id }}）</span>
          </div>
          <div class="row-item">
            <span class="row-label">原文 / 节点 / 边</span>
            <span class="row-value mono">
              {{ refreshResult.events }} / {{ refreshResult.nodes }} / {{ refreshResult.edges }}
            </span>
          </div>
          <div class="row-item">
            <span class="row-label">对账变更</span>
            <span class="row-value mono">{{ refreshResult.reconcile_changed }}</span>
          </div>
          <div class="row-item">
            <span class="row-label">最近对账</span>
            <span class="row-value mono">{{ refreshResult.last_reconcile_at || '—' }}</span>
          </div>
        </div>
        <p v-else-if="refreshError" class="fail-reason">刷新修复失败：{{ refreshError }}</p>
      </SectionCard>
    </div>

    <ConfirmDialog
      v-model:show="ckptOpen"
      title="执行 WAL 检查点？"
      :message="`目标：${writeTargetLabel}`"
      :impacts="[
        '收回主库并截断 WAL，防长期运行 WAL 无界增长（体积可在上方「容量与计数」看到）。',
        '只读操作不受影响；检查点期间若有并发写入，busy 会大于 0，可稍后再执行。',
        '不修改任何原文与衍生知识，只整理 SQLite 的预写日志文件。',
        `写动作只作用于${writeTargetLabel}，联查勾选的其它书目不受影响。`,
      ]"
      confirm-text="执行检查点"
      :loading="ckptRunning"
      @confirm="doCheckpoint"
    />
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 存储体检（观测区）：回答「存储层到底可不可信」。
 *
 * P7 可复原 / P6 失败可见：
 * - 一致性校验（`POST /maintenance/verify`）的每一项都带细节，失败项高亮，接口失败显示错误原文；
 * - 图层操作日志（`GET /maintenance/ops`）是「谁 / 何时 / 因何改了图」的审计，被删节点原数据在 payload 里；
 * - WAL 检查点（`POST /maintenance/checkpoint`）与刷新修复（`POST /repos/{id}/refresh`）都回报真实数字，
 *   不做「点了没反应」的按钮（不可用时禁用并说明原因）。
 *
 * 作用域（规约 §2）：全部 maintenance / repos 调用都带 `useRepoScope()` 的 `effectiveRepoId`。
 */
import { computed, ref, watch } from 'vue'
import { NButton, useMessage } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import StatTile from '@/components/ui/StatTile.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { TableColumn } from '@/components/ui/DataTable.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import * as maintenanceApi from '@/api/maintenance'
import * as reposApi from '@/api/repos'
import type { GraphOpItem, VerifyCheck, VerifyResponse } from '@/api/types'
import { useAsyncAction } from '@/composables/useAsyncAction'
import { useListPage } from '@/composables/useListPage'
import { useRepoScope } from '@/composables/useRepoScope'
import { useHealthStore } from '@/stores/health'
import { useSessionStore } from '@/stores/session'

const message = useMessage()
const health = useHealthStore()
const session = useSessionStore()
const { repo, isJoint, effectiveRepoId, scopeKey, scopeLabel, selectedIds, readRepoIds, repoLabel } =
  useRepoScope()

/**
 * 写动作（WAL 检查点 / 刷新修复）的目标：恰好勾 1 本 → 它；勾 ≥2 本（联查）→ **活动书目**
 * （后端这两个写端点缺省就是活动书目，这里显式点名，不静默打错库）。
 */
const writeRepoId = computed(() => effectiveRepoId.value || repo.activeRepoId)
const writeRepoLabel = computed(() => repoLabel(writeRepoId.value))
const writeRepoName = computed(() => repo.nameOf(writeRepoId.value))

// ── ① 一致性校验（按勾选集合**逐库**跑，前端汇总）────────────────────────────
/**
 * 一次校验 = 一本书目的结论。`POST /maintenance/verify` 只有 `repo_id`、**没有** `repo_ids`，
 * 所以联查态只能逐库跑再把结论汇总（逐项表格带「来自书目」，绝不拿一本的结论冒充全集）。
 */
interface VerifyRun {
  repo_id: string
  repo_name: string
  res: VerifyResponse | null
  error: string
}

const verifyRunning = ref(false)
const verifyError = ref('')
const verifyRuns = ref<VerifyRun[]>([])

const hasVerifyResult = computed(() => verifyRuns.value.length > 0)
/** 真正拿到结论的库数（失败的库不计入） */
const runCount = computed(() => verifyRuns.value.filter((r) => r.res).length)
const verifyOk = computed(
  () => hasVerifyResult.value && verifyRuns.value.every((r) => r.res?.ok === true),
)

/** 逐库校验：单本失败**不吞掉**其它本的结论，错误原文逐库点名（P6 失败可见） */
async function runVerify(): Promise<void> {
  verifyRunning.value = true
  verifyError.value = ''
  try {
    const runs = await Promise.all(
      readRepoIds.value.map(async (repoId) => {
        const name = repoLabel(repoId)
        try {
          const res = await maintenanceApi.verify(repoId || undefined)
          return { repo_id: repoId, repo_name: name, res, error: '' }
        } catch (e) {
          return { repo_id: repoId, repo_name: name, res: null, error: (e as Error).message }
        }
      }),
    )
    verifyRuns.value = runs
    verifyError.value = runs
      .filter((r) => !r.res)
      .map((r) => `${r.repo_name}：${r.error}`)
      .join('；')
  } finally {
    verifyRunning.value = false
  }
}

function resetVerify(): void {
  verifyRuns.value = []
  verifyError.value = ''
}

/** 汇总的校验项（多库时带来源书目与唯一 row_key，逐项都能追到是哪本库的结论） */
type CheckRow = VerifyCheck & { repo_id: string; repo_name: string; row_key: string }
const checks = computed<CheckRow[]>(() =>
  verifyRuns.value.flatMap((run) =>
    (run.res?.checks ?? []).map((c) => ({
      ...c,
      repo_id: run.repo_id,
      repo_name: run.repo_name,
      row_key: `${run.repo_id}:${c.name}`,
    })),
  ),
)
const failedChecks = computed(() => checks.value.filter((c) => !c.ok))

const CHECK_LABELS: Record<string, string> = {
  sqlite_integrity: 'SQLite 页面完整性',
  foreign_keys: '外键一致性',
  events_fts_consistency: '原文 ↔ 原文索引行数一致',
  node_fts_consistency: '节点 ↔ 节点索引行数一致',
  ops_replay_matches_graph: '操作日志重放一致性',
  no_dangling_source_refs: '无悬空源证',
  no_dateless_nodes: '无缺 data 节点',
  // 后端 v1.42 起下发的第 8 项（`maintenance.py` 直接读 graph.json 报文件级残留）
  no_dangling_edges_in_file: '图层文件无悬空边',
}
const checkLabel = (name: string): string => CHECK_LABELS[name] ?? name

const checkColumns = computed<TableColumn[]>(() => {
  const base: TableColumn[] = [{ key: 'name', label: '项目', width: 'lg' }]
  // 多库同跑：逐项必须能看出是哪本库的结论
  if (runCount.value > 1) base.push({ key: 'repo_name', label: '来自书目', width: 'sm' })
  base.push(
    { key: 'ok', label: '结果', width: 'xs', align: 'center' },
    { key: 'detail', label: '细节', width: 'auto' },
  )
  return base
})

const verifyHint = computed(() => {
  if (!hasVerifyResult.value) {
    return '校验 SQLite 完整性 / 外键 / 索引一致 / 操作日志可重放 / 悬空源证 / 缺 data 节点'
  }
  return runCount.value > 1
    ? `只读校验：本次按勾选集合逐库跑了 ${runCount.value} 本，结论逐项汇总（下表带「来自书目」）`
    : '只读校验；结果对应本次运行时的存储状态'
})

// ── ② 容量与计数（sizes / counts 的值可能是数字、字符串或对象）─────────────
/**
 * 逐库结果的 sizes / counts 汇总：**数值项求和**（体积/份数/条数跨库相加有意义），
 * 非数值项逐库点名（绝不拿一本的值冒充全集）。
 */
function mergeRecords(field: 'sizes' | 'counts'): Record<string, unknown> {
  const runs = verifyRuns.value.filter((r) => r.res) as Array<VerifyRun & { res: VerifyResponse }>
  if (!runs.length) return {}
  if (runs.length === 1) return { ...runs[0].res[field] }
  const out: Record<string, unknown> = {}
  const keys = new Set(runs.flatMap((r) => Object.keys(r.res[field])))
  for (const key of keys) {
    const values = runs.map((r) => r.res[field][key])
    const numbers = values.filter((v): v is number => typeof v === 'number')
    if (numbers.length === values.length) {
      out[key] = numbers.reduce((a, b) => a + b, 0)
    } else {
      out[key] = runs.map((r) => `${r.repo_name}=${safeText(r.res[field][key])}`).join(' · ')
    }
  }
  return out
}

const sizes = computed<Record<string, unknown>>(() => mergeRecords('sizes'))
const counts = computed<Record<string, unknown>>(() => mergeRecords('counts'))
const storage = computed(() => health.storage)

/** 安全展示：数字（可按字节格式化）/ 字符串 / 布尔 / 其余一律 JSON */
function jsonText(value: unknown, pretty = false): string {
  try {
    const text = pretty ? JSON.stringify(value, null, 2) : JSON.stringify(value)
    return text ? text : '（空）'
  } catch {
    return '（无法序列化）'
  }
}

function safeText(value: unknown, asBytes = false): string {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'number') return asBytes ? bytes(value) : String(value)
  if (typeof value === 'string') return value || '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return jsonText(value)
}

/** 从体检结果取；未运行时回落到 /health 的现状值 */
function metricText(
  record: Record<string, unknown>,
  key: string,
  opts: { bytes?: boolean; fallback?: number } = {},
): string {
  const raw = record[key]
  if (raw !== undefined && raw !== null) return safeText(raw, opts.bytes === true)
  if (opts.fallback === undefined) return '—'
  return opts.bytes ? bytes(opts.fallback) : String(opts.fallback)
}

const backupCount = computed<number | null>(() => {
  const raw = sizes.value['backups']
  if (typeof raw === 'number') return raw
  const fallback = storage.value?.backups
  return typeof fallback === 'number' ? fallback : null
})

interface Tile {
  label: string
  value: string
  unit?: string
  hint?: string
  tone?: 'default' | 'primary' | 'success' | 'warning' | 'danger'
}

const tiles = computed<Tile[]>(() => {
  const st = storage.value
  const backupTone: Tile['tone'] =
    backupCount.value === null ? 'default' : backupCount.value > 0 ? 'success' : 'warning'
  return [
    {
      label: '主库体积',
      value: metricText(sizes.value, 'db_bytes', { bytes: true, fallback: st?.db_bytes }),
    },
    {
      label: 'WAL 体积',
      value: metricText(sizes.value, 'wal_bytes', { bytes: true, fallback: st?.wal_bytes }),
      hint: '检查点后应回到低位',
    },
    {
      label: '图层文件',
      value: metricText(sizes.value, 'json_bytes', { bytes: true, fallback: st?.json_bytes }),
    },
    {
      label: '备份份数',
      value: metricText(sizes.value, 'backups', { fallback: st?.backups }),
      tone: backupTone,
    },
    { label: '回收站留档', value: metricText(sizes.value, 'trash_items') },
    {
      label: '事件原文',
      value: metricText(counts.value, 'events', { fallback: health.eventLine.total_events }),
    },
    {
      label: '知识节点（衍生）',
      value: metricText(counts.value, 'nodes', { fallback: health.graphLayer.total_nodes }),
    },
    { label: '边（衍生）', value: metricText(counts.value, 'edges') },
    {
      label: '图层操作日志',
      value: metricText(counts.value, 'graph_ops', { fallback: st?.graph_ops }),
      unit: '条',
    },
  ]
})

const KNOWN_SIZES = ['db_bytes', 'wal_bytes', 'json_bytes', 'backups', 'trash_items']
const KNOWN_COUNTS = ['events', 'nodes', 'edges', 'graph_ops']

const extraRows = computed<Array<{ key: string; value: string }>>(() => {
  const out: Array<{ key: string; value: string }> = []
  for (const [key, value] of Object.entries(sizes.value)) {
    if (!KNOWN_SIZES.includes(key)) out.push({ key: `sizes.${key}`, value: safeText(value) })
  }
  for (const [key, value] of Object.entries(counts.value)) {
    if (!KNOWN_COUNTS.includes(key)) out.push({ key: `counts.${key}`, value: safeText(value) })
  }
  return out
})

const capacityHint = computed(() => {
  if (!hasVerifyResult.value) {
    return `尚未校验：显示 /health 的现状（活动书目《${repo.activeRepo?.name ?? '—'}》口径，未必等于顶栏勾选集合）`
  }
  return runCount.value > 1
    ? `本次校验返回的 sizes / counts：勾选 ${runCount.value} 本，**数值项为跨库合计**，非数值项逐库点名`
    : '本次校验返回的 sizes / counts（对应当前作用域书目）'
})

// ── ③ 图层操作日志（真分页：服务端 offset）───────────────────────────────
// ── ③ 图层操作日志（真分页；`GET /maintenance/ops` 只有 `repo_id`，联查靠前端逐库汇总）──
/** 汇总行：操作 + 它属于哪本书目（联查审计必须能看出出处） */
type OpRow = GraphOpItem & { repo_id: string; repo_name: string; row_id: string }

/** 后端点名的分页窗口上限（`maintenance.py` 把 limit 夹到 1..500） */
const OPS_WINDOW_MAX = 500

const {
  items: opItems,
  total: opTotal,
  loading: opsLoading,
  error: opsError,
  offset: opOffset,
  pageSize: opPageSize,
  filters: opFilters,
  reload: opsReload,
  setOffset: opSetOffset,
} = useListPage<OpRow, { scope_key: string }>({
  // 筛选值就是勾选集合的指纹：集合一变，本页重取（`useListPage` 不认数组，故用字符串）
  initialFilters: { scope_key: scopeKey.value },
  pageSize: 10,
  fetch: async ({ limit, offset }) => {
    const ids = readRepoIds.value
    // 每库都取「到本页末尾」的窗口（limit 由后端夹到 500），合并后按时间倒序再切本页
    const window = Math.min(Math.max(offset + limit, limit), OPS_WINDOW_MAX)
    const per = await Promise.all(
      ids.map((repoId) =>
        maintenanceApi.listOps({ repo_id: repoId || undefined, limit: window, offset: 0 }),
      ),
    )
    const rows: OpRow[] = per.flatMap((res, index) =>
      res.ops.map((op) => ({
        ...op,
        repo_id: ids[index],
        repo_name: repoLabel(ids[index]),
        row_id: `${ids[index]}:${op.op_id}`,
      })),
    )
    rows.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0))
    return {
      items: rows.slice(offset, offset + limit),
      total: per.reduce((sum, res) => sum + res.total, 0),
    }
  },
})

const opColumns = computed<TableColumn[]>(() => {
  const base: TableColumn[] = [
    { key: 'created_at', label: '时间', width: 'md' },
    { key: 'op_kind', label: '操作类型', width: 'sm' },
  ]
  if (isJoint.value) base.push({ key: 'repo_name', label: '来自书目', width: 'sm' })
  base.push(
    { key: 'actor', label: '执行者', width: 'sm' },
    { key: 'reason', label: '原因', width: 'md' },
    { key: 'payload', label: '详情（payload 摘要）', width: 'auto' },
  )
  return base
})

const OP_KIND_TEXT: Record<string, string> = {
  node_upsert: '节点写入',
  node_delete: '节点删除',
  edge_upsert: '边写入',
  edge_delete: '边删除',
  graph_clear: '清空图层',
}
const opKindText = (kind: string): string => OP_KIND_TEXT[kind] ?? kind

const selectedOp = ref<OpRow | null>(null)
const selectedOpKey = computed(() => selectedOp.value?.row_id ?? '')

function onOpClick(row: OpRow): void {
  selectedOp.value = selectedOp.value?.row_id === row.row_id ? null : row
}

function payloadText(payload: unknown): string {
  if (payload === undefined || payload === null) return '（无）'
  const text = jsonText(payload)
  return text === '{}' ? '（无）' : text
}

function payloadPretty(payload: unknown): string {
  if (payload === undefined || payload === null) return '（无 payload）'
  return jsonText(payload, true)
}

/** 图层操作日志 `created_at` 是 **UTC** ISO 串（`core/graph_ops.py` 用 `datetime.now(timezone.utc).isoformat()`）：
 *  必须转本地时间（只切字符串会让东八区用户看到「8 小时前」的操作时间）。 */
function shortTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  // 无效值回退原样（不渲染 Invalid Date）
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}

// ── ④ WAL 检查点（写动作：目标是 `writeRepoId`，联查态 = 活动书目，界面点名）──────
const checkpoint = useAsyncAction(() =>
  maintenanceApi.checkpoint(writeRepoId.value || undefined),
)
const {
  running: ckptRunning,
  error: ckptError,
  lastResult: ckptResult,
  run: runCheckpoint,
} = checkpoint
const ckptOpen = ref(false)

async function doCheckpoint(): Promise<void> {
  ckptOpen.value = false
  const res = await runCheckpoint()
  if (!res) return // 失败原文已常驻显示在该区块
  message.success(`WAL 检查点完成：已收回并截断 ${res.checkpointed_frames} 帧`)
  await session.commit()
  await health.refresh()
}

// ── ⑤ 刷新修复书目（写动作：目标是 `writeRepoId`）─────────────────────────
const refresh = useAsyncAction((repoId: string) => reposApi.refreshRepo(repoId))
const {
  running: refreshRunning,
  error: refreshError,
  lastResult: refreshResult,
  run: runRefresh,
} = refresh

const canRefreshRepo = computed(() => Boolean(writeRepoId.value))

/** 写动作的目标：恰好勾 1 本 = 该库；联查 = 活动书目（后端写端点缺省口径） */
const writeTargetLabel = computed(() =>
  effectiveRepoId.value
    ? `书目《${writeRepoName.value}》（顶栏勾选）`
    : `活动书目《${writeRepoName.value}》（联查态下的写目标）`,
)

async function doRefreshRepo(): Promise<void> {
  const repoId = writeRepoId.value
  if (!repoId) {
    message.warning('当前没有可用的书目（活动书目未加载）：无法确定要重载哪一本')
    return
  }
  const res = await runRefresh(repoId)
  if (!res) return // 失败原文已常驻显示在该区块
  message.success(res.message || '书目已刷新修复')
  await session.commit()
  await health.refresh()
  await repo.load()
  void opsReload()
}

// ── 勾选集合切换：旧结论不再对应当前集合，回到「未运行」引导态 ──────────────
watch(scopeKey, (key) => {
  opFilters.scope_key = key
  selectedOp.value = null
  resetVerify()
  checkpoint.reset()
  refresh.reset()
  void health.refresh()
  void opsReload()
})

async function reloadAll(): Promise<void> {
  await Promise.all([opsReload(), health.refresh()])
  if (hasVerifyResult.value) await runVerify()
}

function bytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(2)} MiB`
}
</script>

<style scoped>
.sc-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
}
/* 卡片不许被 flex 压缩（各卡自带 overflow:hidden，自动最小高度为 0）：
   否则内容超高时会被压扁裁掉，而不是让外层滚动 */
.sc-scroll > * {
  flex-shrink: 0;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(22ch, 1fr));
  gap: var(--dpim-space-2);
}
.note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.5;
}
.warn-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-warning);
  line-height: 1.5;
}
.mono {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.verdict {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-3) var(--dpim-space-4);
  border-radius: var(--dpim-radius-sm);
}
.verdict--ok {
  background: var(--dpim-success-soft);
  color: var(--dpim-success);
}
.verdict--bad {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.verdict-mark {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-lg);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.verdict-text {
  font-size: var(--dpim-fs-md);
  line-height: 1.5;
  word-break: break-word;
}
.check-name {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
}
.check-label {
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
}
.check-label--fail {
  color: var(--dpim-danger);
  font-weight: 600;
}
.check-key {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
}
.check-badge {
  display: inline-block;
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-xs);
  font-weight: 700;
  white-space: nowrap;
}
.check-badge--ok {
  background: var(--dpim-success-soft);
  color: var(--dpim-success);
}
.check-badge--fail {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.check-detail {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  word-break: break-word;
}
.check-detail--fail {
  color: var(--dpim-danger);
}
.ops-card {
  min-height: 0;
  max-height: 52vh;
}
.tag {
  display: inline-block;
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  white-space: nowrap;
  background: var(--dpim-surface-2);
  color: var(--dpim-text-2);
}
.tag--node_upsert,
.tag--edge_upsert {
  background: var(--dpim-derived-bg);
  color: var(--dpim-derived-fg);
}
.tag--node_delete,
.tag--edge_delete,
.tag--graph_clear {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--dpim-text-2);
  line-height: 1.5;
}
.payload-brief {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  word-break: break-all;
}
.payload-box {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
}
.payload-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--dpim-space-2);
}
.payload-title {
  font-size: var(--dpim-fs-sm);
  font-weight: 600;
  color: var(--dpim-text-2);
}
.payload-json {
  margin: 0;
  padding: var(--dpim-space-3);
  background: var(--dpim-inset);
  box-shadow: var(--dpim-inset-shadow);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 18vh;
  overflow: auto;
}
.act-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--dpim-space-4);
  padding: var(--dpim-space-2) 0;
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
}
.act-text {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
  min-width: 0;
}
.act-title {
  margin: 0;
  font-size: var(--dpim-fs-md);
  font-weight: 600;
  color: var(--dpim-text);
}
.act-desc {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.5;
}
.result-rows {
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
  flex: 0 0 22ch;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.row-value {
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
  word-break: break-word;
}
.fail-reason {
  margin: 0;
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
  border-radius: var(--dpim-radius-sm);
  font-size: var(--dpim-fs-sm);
  word-break: break-word;
}
</style>
