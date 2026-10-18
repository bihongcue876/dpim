<template>
  <PageShell
    zone="维护"
    title="备份与恢复"
    description="可复原：整库备份、清单摘要、恢复路径（恢复须停服务，用本地 CLI）"
  >
    <template #actions>
      <n-button type="primary" size="small" @click="openCreate">新建备份</n-button>
    </template>

    <SectionCard v-if="createError" title="新建备份失败" hint="后端返回的原文（点「关闭」前一直可见）。">
      <p class="fail-text">{{ createError }}</p>
      <div class="inline-actions">
        <n-button size="small" quaternary @click="clearCreateError">关闭</n-button>
      </div>
    </SectionCard>

    <SectionCard v-if="listError && backups.length" title="备份清单读取失败">
      <p class="fail-text">{{ listError }}</p>
      <div class="inline-actions">
        <n-button size="small" :loading="loading" @click="loadBackups">重试</n-button>
      </div>
    </SectionCard>

    <SectionCard v-if="lastBackup" title="最近一次备份">
      <div class="rows">
        <div class="row-item">
          <span class="row-label">时间戳</span>
          <span class="row-value mono">{{ lastBackup.stamp }}</span>
        </div>
        <div class="row-item">
          <span class="row-label">备份目录</span>
          <span class="row-value mono">{{ lastBackup.backup_dir }}</span>
        </div>
        <div class="row-item">
          <span class="row-label">裁剪旧备份</span>
          <span class="row-value">{{ lastBackup.pruned }} 份</span>
        </div>
        <div class="row-item">
          <span class="row-label">清单摘要</span>
          <span class="row-value">{{ manifestSummary(lastBackup.manifest) }}</span>
        </div>
      </div>
    </SectionCard>

    <Toolbar>
      <span class="scope-note">书目作用域：{{ scope.scopeLabel.value }}</span>
      <span v-if="scope.isJoint.value" class="warn-note">
        联查（勾选 {{ scope.selectedIds.value.length }} 本）：清单是各库备份的汇总；
        「新建备份」是写动作，只作用于活动书目《{{ writeRepoName }}》，不会写进联查的其它库。
      </span>
      <span class="scope-note">备份按份数保留（最近 {{ KEEP_BACKUPS }} 份），超出会裁剪最旧的。</span>
      <template #right>
        <n-button size="small" quaternary :loading="loading" @click="loadBackups">刷新</n-button>
      </template>
    </Toolbar>

    <SectionCard
      title="备份清单"
      hint="每份备份 = SQLite 在线副本（VACUUM INTO）+ graph.json + manifest.json，落在库目录的 backups/<时间戳>/ 下"
      flush
    >
      <DataTable
        :columns="columns"
        :rows="backups"
        row-key="row_id"
        :loading="loading"
        :error="listError"
        empty-text="这本书目还没有备份"
        empty-hint="点右上角「新建备份」生成第一份；备份是恢复的唯一退路。"
      >
        <template #cell-repo_name="{ row }">
          <span class="repo-name">{{ row.repo_name }}</span>
        </template>
        <template #cell-stamp="{ row }">
          <span class="mono">{{ row.stamp }}</span>
        </template>
        <template #cell-bytes="{ row }">
          <span class="num">{{ bytes(row.bytes) }}</span>
        </template>
        <template #cell-path="{ row }">
          <span class="path">{{ row.path }}</span>
        </template>
        <template #cell-summary="{ row }">
          <span class="summary">{{ manifestSummary(row.manifest) }}</span>
        </template>
        <template #empty-extra>
          <n-button size="small" type="primary" @click="openCreate">新建备份</n-button>
        </template>
      </DataTable>
    </SectionCard>

    <SectionCard
      title="恢复（须停服务 · 本地 CLI）"
      hint="本页刻意不提供在线恢复按钮：恢复会整文件覆盖 memory.db 与 graph.json，运行中的服务内存图会陈旧。"
    >
      <ol class="steps">
        <li>先停掉后端服务（正在运行的 serve）。恢复会先抢跨进程锁，服务还在时会被拒绝。</li>
        <li>
          在仓库根的 <code class="path">dpim/</code> 目录下执行本地 CLI（
          <code class="path">stamp</code> 取上表「时间」列）：
        </li>
      </ol>
      <pre class="cmd">cd dpim
python main.py restore &lt;stamp&gt; --yes</pre>
      <p class="example">
        以最新一份备份为例：
        <code class="path">cd dpim; python main.py restore {{ exampleStamp }} --yes</code>
      </p>
      <ul class="notes">
        <li>不带 <code class="path">--yes</code> 只会打印一行提示并退出，不会覆盖任何文件。</li>
        <li>恢复前会先给当前状态做一次安全备份（恢复错了还能退回来），随后覆盖 <code class="path">memory.db</code> 与 <code class="path">graph.json</code>，并清掉陈旧的 -wal / -shm。</li>
        <li>
          本地 CLI <strong>没有 --repo 参数</strong>：它按 <code class="path">DPIM_MEMORY_DB_PATH</code> /
          <code class="path">DPIM_GRAPH_JSON_PATH</code> 定位库。要恢复某本书目，先把这两个环境变量指向该库的两个文件再执行。
        </li>
        <li v-if="libraryDir">
          当前写入目标的书目（{{ scope.repoLabel(writeRepoId) }}，由上表该库备份路径推出）：
          <code class="path">DPIM_MEMORY_DB_PATH={{ libraryDir }}/memory.db</code>
          <code class="path">DPIM_GRAPH_JSON_PATH={{ libraryDir }}/graph.json</code>
        </li>
        <li>恢复完成后重启服务使其生效。</li>
      </ul>
    </SectionCard>

    <n-modal :show="createOpen" @update:show="(v: boolean) => (createOpen = v)">
      <div class="modal-box">
        <h3 class="modal-title">新建备份</h3>
        <p class="modal-hint">
          备份内容：SQLite 在线副本（VACUUM INTO，一致且紧凑）+ graph.json + manifest.json（事件数 /
          节点数 / 操作日志数 / 版本）。
        </p>
        <p class="modal-hint">备份目标：{{ scope.repoLabel(writeRepoId) }}</p>
        <p v-if="scope.isJoint.value" class="warn-note">
          当前勾选了 {{ scope.selectedIds.value.length }} 本书目（联查）：清单一栏汇总多本，
          但「新建备份」是写动作，只作用于活动书目《{{ writeRepoName }}》——要备份别的书目请只勾选它。
        </p>
        <FieldRow label="备注" hint="可选，≤200 字，写进 manifest.json 便于日后辨认">
          <n-input
            v-model:value="createNote"
            size="small"
            placeholder="例如：改分组前的备份"
          />
        </FieldRow>
        <p class="modal-hint">
          备份按份数保留（最近 {{ KEEP_BACKUPS }} 份），超出会裁剪最旧的；备份目录写在库目录的 backups/ 下。
        </p>
        <p v-if="createError" class="fail-text">{{ createError }}</p>
        <div class="modal-actions">
          <n-button size="small" quaternary @click="createOpen = false">取消</n-button>
          <n-button size="small" type="primary" :loading="creating" @click="doCreate">
            开始备份
          </n-button>
        </div>
      </div>
    </n-modal>
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 备份与恢复（维护区，规约 §4.9）：可复原。
 *
 * - 主操作「新建备份」：可填备注，成功后显式回报 backup_dir / stamp / pruned；
 * - 清单挑出 manifest 里的**事件数 / 节点数 / 操作日志数 / 版本**（挑不到则退回条目数）；
 * - **恢复只做只读展示 + 指引**（规约 §4.9 与「不在本规约范围」明确要求，不提供在线恢复按钮）：
 *   命令已对照 `dpim/interface/cli.py` 的 `restore` 命令与 `dpimCLI/README.md` 核实。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NInput, NModal, useMessage } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import FieldRow from '@/components/ui/FieldRow.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { TableColumn } from '@/components/ui/DataTable.vue'
import * as maintenanceApi from '@/api/maintenance'
import type { BackupListResponse, BackupResponse } from '@/api/types'
import { useAsyncAction } from '@/composables/useAsyncAction'
import { useRepoScope } from '@/composables/useRepoScope'
import { useSessionStore } from '@/stores/session'

/** 后端 `core/maintenance.py` 的 KEEP_BACKUPS：备份按份数保留，超出裁剪最旧的 */
const KEEP_BACKUPS = 5

type BackupItem = BackupListResponse['backups'][number]
/** 汇总行：备份条目 + 它属于哪本书目（联查清单必须能看出出处） */
type BackupRow = BackupItem & { repo_id: string; repo_name: string; row_id: string }

const message = useMessage()
const scope = useRepoScope()
const session = useSessionStore()

const columns = computed<TableColumn[]>(() => {
  const base: TableColumn[] = [
    { key: 'stamp', label: '时间', width: 'md', mono: true },
    { key: 'bytes', label: '体积', width: 'sm', align: 'right' },
    { key: 'summary', label: '清单摘要', width: 'auto' },
    { key: 'path', label: '路径', width: 'lg', mono: true },
  ]
  if (scope.isJoint.value) base.splice(1, 0, { key: 'repo_name', label: '来自书目', width: 'sm' })
  return base
})

const backups = ref<BackupRow[]>([])
const loading = ref(false)
const listError = ref('')
const lastBackup = ref<BackupResponse | null>(null)

/**
 * 写动作（新建备份）的目标：恰好勾 1 本 → 它；勾 ≥2 本（联查）→ **活动书目**
 * （后端 `/maintenance/backup` 的缺省口径就是活动书目，这里显式点名，不静默）。
 */
const writeRepoId = computed(() => scope.effectiveRepoId.value || scope.repo.activeRepoId)
const writeRepoName = computed(() => scope.repo.activeRepo?.name ?? '—')

/** 写动作目标书目的备份（恢复指引的 stamp 与库目录都必须与「新建备份」同一本，不能张冠李戴） */
const writeRepoBackups = computed(() =>
  backups.value.filter((b) => b.repo_id === writeRepoId.value),
)

const {
  running: creating,
  error: createError,
  run: runCreate,
} = useAsyncAction<[string], BackupResponse>((note) =>
  maintenanceApi.createBackup(note, writeRepoId.value || undefined),
)

/** 恢复示例：用目标书目最新一份备份的时间戳（没有备份时留占位） */
const exampleStamp = computed(() => writeRepoBackups.value[0]?.stamp ?? '<上表中的时间戳>')

/** 由备份路径反推库目录（`<库目录>/backups/<stamp>` 去掉最后两段） */
const libraryDir = computed(() => {
  const path = writeRepoBackups.value[0]?.path
  if (!path) return ''
  const sep = path.includes('\\') ? '\\' : '/'
  return path.split(sep).slice(0, -2).join(sep)
})

/**
 * 取清单：对勾选的每本书目各取一次（`GET /maintenance/backups` 只有 `repo_id`），
 * 汇总后按时间戳倒序。单本书目失败**不吞掉**其它书目的结果，错误原文逐库点名（P6）。
 */
async function loadBackups(): Promise<void> {
  loading.value = true
  try {
    const results = await Promise.all(
      scope.readRepoIds.value.map(async (repoId) => {
        try {
          const res = await maintenanceApi.listBackups(repoId || undefined)
          return { repoId, res, error: '' }
        } catch (e) {
          return { repoId, res: null, error: (e as Error).message }
        }
      }),
    )
    const rows: BackupRow[] = []
    const failures: string[] = []
    for (const r of results) {
      if (!r.res) {
        failures.push(`${scope.repoLabel(r.repoId)}：${r.error}`)
        continue
      }
      for (const item of r.res.backups) {
        rows.push({
          ...item,
          repo_id: r.repoId,
          repo_name: scope.repoLabel(r.repoId),
          row_id: `${r.repoId}:${item.stamp}`,
        })
      }
    }
    rows.sort((a, b) => (a.stamp < b.stamp ? 1 : a.stamp > b.stamp ? -1 : 0))
    // 全部库都失败 → **不动已有清单**（旧数据仍可查看），只把错误原文报出来（P6）
    if (!failures.length || rows.length) backups.value = rows
    listError.value = failures.join('；')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadBackups()
})

// ── 勾选集合变化：清单 / 「最近一次备份」/ 恢复指引（stamp 与库目录都由备份清单反推）
//    全属旧书目，必须重取并清空——否则用户会以为当前书目已有备份而省掉备份 ──
watch(scope.scopeKey, () => {
  lastBackup.value = null
  createError.value = ''
  void loadBackups()
})

const createOpen = ref(false)
const createNote = ref('')

function openCreate(): void {
  createNote.value = ''
  createOpen.value = true
}

function clearCreateError(): void {
  createError.value = ''
}

async function doCreate(): Promise<void> {
  const res = await runCreate(createNote.value.trim())
  if (!res) return
  lastBackup.value = res
  createOpen.value = false
  createNote.value = ''
  message.success(`备份完成：${res.stamp}`)
  await loadBackups()
  await session.commit()
}

function bytes(value: number | undefined): string {
  if (value === undefined || value === null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(2)} MiB`
}

/** 清单摘要：挑事件数 / 节点数 / 操作日志数 / 版本；挑不到就报条目数 */
function manifestSummary(manifest: Record<string, unknown> | undefined): string {
  const m = manifest ?? {}
  const parts: string[] = []
  const pick = (label: string, key: string): void => {
    const value = m[key]
    if (typeof value === 'number') parts.push(`${label} ${value}`)
    else if (typeof value === 'string' && value) parts.push(`${label} ${value}`)
  }
  pick('事件', 'total_events')
  pick('节点', 'total_nodes')
  pick('操作日志', 'graph_ops')
  pick('存储版本', 'schema_version')
  pick('图层版本', 'graph_format_version')
  if (!parts.length) {
    const count = Object.keys(m).length
    return count ? `清单 ${count} 个条目` : '无清单'
  }
  const note = m.note
  if (typeof note === 'string' && note.trim()) parts.push(`备注「${note.trim()}」`)
  return parts.join(' · ')
}
</script>

<style scoped>
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
  width: 110px;
  flex-shrink: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
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
.mono,
.path {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  word-break: break-all;
  user-select: text;
}
.num {
  font-variant-numeric: tabular-nums;
}
.summary {
  color: var(--dpim-text-2);
  line-height: 1.5;
}
.repo-name {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
}
.scope-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.warn-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-warning);
  line-height: 1.5;
}
.steps,
.notes {
  margin: 0;
  padding-left: var(--dpim-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text-2);
  line-height: 1.6;
}
.cmd {
  margin: 0;
  padding: var(--dpim-space-3);
  background: var(--dpim-inset);
  box-shadow: var(--dpim-inset-shadow);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text);
  white-space: pre-wrap;
  word-break: break-all;
  user-select: text;
}
.example {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.6;
}
.fail-text {
  margin: 0;
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
  border-radius: var(--dpim-radius-sm);
  font-size: var(--dpim-fs-md);
  line-height: 1.5;
  word-break: break-word;
}
.inline-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--dpim-space-2);
}
.modal-box {
  width: min(560px, calc(100vw - var(--dpim-space-6)));
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
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
.modal-hint {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.5;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--dpim-space-2);
  margin-top: var(--dpim-space-2);
}
</style>
