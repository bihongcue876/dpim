<template>
  <PageShell
    zone="维护"
    title="回收站"
    description="删除可回收：事件与节点在物理删除前留档、清空图层前自动留档整图，按原 ID 恢复"
  >
    <template #actions>
      <n-button
        type="primary"
        size="small"
        :disabled="!selected"
        :loading="restoring"
        @click="askRestore(selected)"
      >
        恢复选中
      </n-button>
    </template>

    <SectionCard v-if="restoreError" title="恢复失败" hint="后端返回的原文（点「关闭」前一直可见）。">
      <p class="fail-text">{{ restoreError }}</p>
      <div class="inline-actions">
        <n-button size="small" quaternary @click="clearRestoreError">关闭</n-button>
      </div>
    </SectionCard>

    <SectionCard v-if="restoreNotice" title="上次恢复结果">
      <p class="notice-text">{{ restoreNotice }}</p>
      <div class="inline-actions">
        <n-button size="small" quaternary @click="restoreNotice = ''">关闭</n-button>
      </div>
    </SectionCard>

    <SectionCard v-if="listError && items.length" title="留档清单读取失败">
      <p class="fail-text">{{ listError }}</p>
      <div class="inline-actions">
        <n-button size="small" :loading="loading" @click="loadTrash">重试</n-button>
      </div>
    </SectionCard>

    <Toolbar>
      <span class="scope-note">书目作用域：{{ scope.scopeLabel.value }}</span>
      <span v-if="scope.isJoint.value" class="warn-note">
        联查（勾选 {{ scope.selectedIds.value.length }} 本）：清单是各库留档的汇总；
        恢复是写动作，按**每条留档所属的书目**下发 repo_id 恢复（不会落到别的库）。
      </span>
      <span class="scope-note">
        {{ selected ? `已选中：${kindText(selected.kind)} ${selected.id} · 来自${scope.repoLabel(selected.repo_id)}` : '在上表点选一行，再点右上角「恢复选中」' }}
      </span>
      <template #right>
        <n-button size="small" quaternary :loading="loading" @click="loadTrash">刷新</n-button>
      </template>
    </Toolbar>

    <SectionCard
      title="留档清单"
      hint="删除事件或节点时，后端先把整行数据写成 JSON 留档，再做物理删除；清空图层时留档整图"
      flush
    >
      <template #actions>
        <span v-if="dir" class="dir-note">
          留档目录 <code class="path">{{ dir }}</code>
        </span>
      </template>
      <DataTable
        :columns="columns"
        :rows="items"
        row-key="row_id"
        :loading="loading"
        :error="listError"
        :selected-key="selected?.row_id ?? ''"
        empty-text="暂无留档"
        empty-hint="删除事件或节点、或清空图层时会自动留档到这里；留档按原 ID 可恢复。"
        @row-click="onRowClick"
      >
        <template #cell-repo_name="{ row }">
          <span class="repo-name">{{ scope.repoLabel(row.repo_id) }}</span>
        </template>
        <template #cell-archived_at="{ row }">
          <span class="mono">{{ shortTime(row.archived_at) }}</span>
        </template>
        <template #cell-kind="{ row }">
          <span class="tag" :class="`tag--${row.kind}`">{{ kindText(row.kind) }}</span>
        </template>
        <template #cell-id="{ row }">
          <span class="path">{{ row.id }}</span>
        </template>
        <template #cell-size="{ row }">
          <span class="num">{{ bytes(row.size) }}</span>
        </template>
        <template #cell-title="{ row }">
          <span class="title">{{ row.title || '（留档无标题/摘要）' }}</span>
        </template>
        <template #cell-actions="{ row }">
          <n-button size="tiny" :loading="restoringId === row.row_id" @click="askRestore(row)">
            恢复
          </n-button>
        </template>
      </DataTable>
    </SectionCard>

    <ConfirmDialog
      v-model:show="showConfirm"
      :title="pending?.kind === 'graph' ? '恢复整图留档？' : '按原 ID 恢复这条留档？'"
      :message="pending ? `${kindText(pending.kind)} ${pending.id}` : ''"
      :impacts="confirmImpacts"
      confirm-text="恢复"
      :loading="restoring"
      @confirm="doRestore"
      @cancel="pending = null"
    />
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 回收站（维护区，规约 §4.10）：删除可回收。
 *
 * 后端在物理删除前把整行数据留档到 `<库目录>/trash/{events,nodes}/<id>.json`；
 * 恢复是**按原 ID** 放回（已存在同 ID → 409，绝不覆盖现有数据）。
 * 留档目录路径直接显示在清单表头，等宽可选中复制。
 *
 * 书目作用域（勾选集合）：`GET /trash` 只有 `repo_id` 单库参数、**没有** `repo_ids`，
 * 因此这里对勾选的每本书目各取一次、前端汇总（并标出「来自书目」）；
 * 恢复是写动作，`POST /trash/restore` 本就接受 `repo_id`——按**该条留档所属的书目**下发，
 * 绝不静默落到活动书目（否则汇总清单里点别库的留档会 404「留档不存在」）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, useMessage } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { TableColumn } from '@/components/ui/DataTable.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import * as trashApi from '@/api/trash'
import type { TrashItem } from '@/api/types'
import { useAsyncAction } from '@/composables/useAsyncAction'
import { useRepoScope } from '@/composables/useRepoScope'
import { useSessionStore } from '@/stores/session'

/** 汇总行：留档条目 + 它属于哪本书目（联查清单必须能看出出处） */
type TrashRow = TrashItem & { repo_id: string; repo_name: string; row_id: string }

const message = useMessage()
const scope = useRepoScope()
const session = useSessionStore()

const columns = computed<TableColumn[]>(() => {
  const base: TableColumn[] = [
    { key: 'archived_at', label: '留档时间', width: 'md', mono: true },
    { key: 'kind', label: '类型', width: 'xs' },
    { key: 'id', label: '原 ID', width: 'lg', mono: true },
    { key: 'size', label: '体积', width: 'sm', align: 'right' },
    { key: 'title', label: '标题 / 摘要', width: 'auto' },
  ]
  if (scope.isJoint.value) base.push({ key: 'repo_name', label: '来自书目', width: 'sm' })
  base.push({ key: 'actions', label: '操作', width: 'xs', align: 'right' })
  return base
})

const items = ref<TrashRow[]>([])
const dir = ref('')
const loading = ref(false)
const listError = ref('')
const selected = ref<TrashRow | null>(null)
const pending = ref<TrashRow | null>(null)
const showConfirm = ref(false)
const restoreNotice = ref('')

const {
  running: restoring,
  error: restoreError,
  run: runRestore,
} = useAsyncAction<[TrashRow], { message: string }>((item) =>
  // 写动作的目标 = 该条留档所属书目（`POST /trash/restore` 的 `repo_id` 参数）
  trashApi.restoreTrash(item.kind, item.id, item.repo_id || undefined),
)

/** 正在恢复的那一行（逐行按钮的 loading） */
const restoringId = computed(() => (restoring.value ? (pending.value?.row_id ?? '') : ''))

const confirmImpacts = computed<string[]>(() => {
  const kind = pending.value?.kind
  const target = pending.value
    ? `恢复目标：${scope.repoLabel(pending.value.repo_id)}（按这条留档所属的书目下发 repo_id）。`
    : ''
  if (kind === 'graph') {
    return [
      target,
      '整图留档（清空图层时自动生成）：恢复是**合并式**——缺的节点与边补回，已存在的跳过，**不覆盖**现有内容。',
      '边只在两端节点都在图中时才补回，绝不造悬空边。',
      '原文（时序事件存储）不受影响；本条留档恢复后移入 trash/restored/。',
    ].filter(Boolean)
  }
  return [
    target,
    '按**原 ID** 恢复：事件会重新入库并重建全文索引；节点会把本体与源证放回，关联边能恢复多少恢复多少。',
    kind === 'event'
      ? '既有图节点指向该事件的源证会随之重新对上。'
      : '节点恢复不触碰线层原文。',
    '若该 ID 已存在，后端返回 409 并拒绝恢复（不会覆盖现有数据）。',
    '恢复成功后留档文件移入 trash/restored/（保留「恢复过什么」的痕迹，不删原件）。',
  ].filter(Boolean)
})

function kindText(kind: TrashItem['kind'] | undefined): string {
  if (kind === 'event') return '事件'
  if (kind === 'node') return '节点'
  if (kind === 'graph') return '整图'
  return '—'
}

/**
 * 取清单：对勾选的每本书目各取一次（`GET /trash` 只有 `repo_id`），汇总后按留档时间倒序。
 * 单本书目失败**不吞掉**其它书目的结果，错误原文逐库点名（P6 失败可见）。
 */
async function loadTrash(): Promise<void> {
  loading.value = true
  const ids = scope.readRepoIds.value
  try {
    const results = await Promise.all(
      ids.map(async (repoId) => {
        try {
          const res = await trashApi.listTrash(repoId || undefined)
          return { repoId, res, error: '' }
        } catch (e) {
          return { repoId, res: null, error: (e as Error).message }
        }
      }),
    )
    const rows: TrashRow[] = []
    const dirs: string[] = []
    const failures: string[] = []
    for (const r of results) {
      if (!r.res) {
        failures.push(`${scope.repoLabel(r.repoId)}：${r.error}`)
        continue
      }
      if (r.res.dir) dirs.push(r.res.dir)
      for (const item of r.res.items) {
        rows.push({
          ...item,
          repo_id: r.repoId,
          repo_name: scope.repoLabel(r.repoId),
          row_id: `${r.repoId}:${item.path}`,
        })
      }
    }
    rows.sort((a, b) => (a.archived_at < b.archived_at ? 1 : a.archived_at > b.archived_at ? -1 : 0))
    // 全部库都失败 → **不动已有清单**（旧数据仍可查看），只把错误原文报出来（P6）
    if (!failures.length || rows.length) {
      items.value = rows
      dir.value =
        dirs.length > 1 ? `${dirs.length} 本书目各自的留档目录（见下表「来自书目」）` : (dirs[0] ?? '')
    }
    listError.value = failures.join('；')
    if (selected.value && !items.value.some((i) => i.row_id === selected.value?.row_id)) {
      selected.value = null
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadTrash()
})

// ── 勾选集合变化：清单与选中项都属旧书目，必须重取（否则「恢复」按新作用域发请求 →
//    404「留档不存在」，用户以为救不回来） ──
watch(scope.scopeKey, () => {
  selected.value = null
  pending.value = null
  showConfirm.value = false
  restoreNotice.value = ''
  void loadTrash()
})

function onRowClick(row: TrashRow): void {
  selected.value = row
}

function askRestore(item: TrashRow | null): void {
  if (!item) return
  pending.value = item
  showConfirm.value = true
}

function clearRestoreError(): void {
  restoreError.value = ''
}

async function doRestore(): Promise<void> {
  const item = pending.value
  if (!item) return
  const res = await runRestore(item)
  showConfirm.value = false
  pending.value = null
  if (!res) return
  restoreNotice.value = res.message
  selected.value = null
  message.success('留档已恢复')
  await loadTrash()
  await session.commit()
}

/** 留档 `archived_at` 是 **UTC** ISO 串（`core/trash.py` 用 `datetime.now(timezone.utc).isoformat()`）：
 *  必须转本地时间（只切字符串会让东八区用户看到「8 小时前」的留档时间）。 */
function shortTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  // 无效值回退原样（不渲染 Invalid Date）
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}

function bytes(value: number | undefined): string {
  if (value === undefined || value === null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(2)} MiB`
}
</script>

<style scoped>
.scope-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.warn-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-warning);
  line-height: 1.5;
}
.dir-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  word-break: break-all;
}
.repo-name {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
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
.title {
  color: var(--dpim-text-2);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tag {
  display: inline-block;
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  white-space: nowrap;
}
.tag--event {
  background: var(--dpim-origin-bg);
  color: var(--dpim-origin-fg);
}
.tag--node {
  background: var(--dpim-derived-bg);
  color: var(--dpim-derived-fg);
}
.tag--graph {
  background: var(--dpim-warning-soft);
  color: var(--dpim-warning);
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
.notice-text {
  margin: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text-2);
  line-height: 1.6;
  word-break: break-word;
}
.inline-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--dpim-space-2);
}
</style>
