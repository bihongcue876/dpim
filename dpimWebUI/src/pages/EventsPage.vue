<template>
  <PageShell zone="查阅" title="信息列表" description="查原文、修订原文、看衍生关联">
    <template #actions>
      <n-button type="primary" size="small" @click="openCreate">新建事件</n-button>
    </template>

    <Toolbar>
      <n-select
        v-model:value="list.filters.type"
        size="small"
        class="f-select"
        :options="TYPE_OPTIONS"
        placeholder="类型"
        clearable
        @update:value="list.applyFilters()"
      />
      <n-select
        v-model:value="list.filters.status"
        size="small"
        class="f-select"
        :options="STATUS_OPTIONS"
        placeholder="状态"
        clearable
        @update:value="list.applyFilters()"
      />
      <n-input
        v-model:value="list.filters.query"
        size="small"
        class="f-input"
        placeholder="关键词（原文全文检索）"
        clearable
        @keyup.enter="list.applyFilters()"
      />
      <n-button size="small" @click="list.applyFilters()">查询</n-button>
      <n-button size="small" quaternary @click="list.resetFilters()">重置</n-button>
      <template #right>
        <span class="scope-note">{{ scope.scopeLabel.value }}</span>
        <n-button size="small" quaternary :loading="list.loading.value" @click="reloadAll">
          刷新
        </n-button>
      </template>
    </Toolbar>

    <!-- 新建事件的常驻结果区（P6）：指令不落库、后端未返回 event_id 都不许报「已写入」 -->
    <SectionCard v-if="createResult" :title="createResult.title" :hint="createResult.hint">
      <p class="result-detail">{{ createResult.detail }}</p>
      <p v-if="createResult.error" class="fail-reason">{{ createResult.error }}</p>
      <div class="inline-actions">
        <n-button size="small" quaternary @click="createResult = null">关闭</n-button>
      </div>
    </SectionCard>

    <div class="split">
      <div class="split-list">
        <DataTable
          :columns="columns"
          :rows="list.items.value"
          row-key="event_id"
          :loading="list.loading.value"
          :error="list.error.value"
          :selected-key="selectedId"
          empty-text="没有事件"
          empty-hint="到「信息传入」页写入第一条原文，或放宽当前筛选。"
          :total="list.total.value"
          :page-size="list.pageSize.value"
          :offset="list.offset.value"
          @row-click="onRowClick"
          @update:offset="list.setOffset"
        >
          <template #cell-event_type="{ row }">
            <span class="tag" :class="`tag--${row.event_type}`">{{ typeText(row.event_type) }}</span>
          </template>
          <template #cell-status="{ row }">
            <span class="status" :class="`status--${row.status}`">{{ statusText(row.status) }}</span>
          </template>
          <template #cell-raw_content="{ row }">
            <span class="preview">{{ row.raw_content }}</span>
          </template>
          <template #cell-created_at="{ row }">
            <span class="time">{{ shortTime(row.created_at) }}</span>
          </template>
          <template #cell-repo_name="{ row }">
            <span class="time">{{ row.repo_name || '—' }}</span>
          </template>
        </DataTable>
      </div>

      <div class="split-detail">
        <DetailPanel
          :title="detail ? '事件原文' : '未选择事件'"
          :subtitle="detail ? detail.event_id : '在左侧列表选择一条事件'"
        >
          <template #head-actions>
            <OriginBadge kind="origin" />
          </template>

          <template v-if="detail" #meta>
            <span>类型：{{ typeText(detail.event_type) }}</span>
            <span>状态：{{ statusText(detail.status) }}</span>
            <span>写入：{{ shortTime(detail.created_at) }}</span>
            <span class="mono">hash：{{ detail.content_hash }}</span>
          </template>

          <StateBlock
            v-if="!detail"
            empty-text="未选择事件"
            hint="左侧点选一行即可查看原文与其衍生关联。"
            fixed-height
          />
          <StateBlock
            v-else-if="detailLoading"
            loading
            fixed-height
          />
          <StateBlock v-else-if="detailError" :error="detailError" fixed-height>
            <template #retry>
              <n-button size="small" @click="loadDetail(selectedId)">重试</n-button>
            </template>
          </StateBlock>

          <template v-else>
            <section class="block">
              <div class="block-head">
                <OriginBadge kind="origin" text="原文 · 仅人类可修订" />
                <n-button
                  v-if="!editing"
                  size="tiny"
                  quaternary
                  @click="startEdit"
                >
                  修订
                </n-button>
              </div>
              <template v-if="editing">
                <n-input
                  v-model:value="draftContent"
                  type="textarea"
                  :autosize="{ minRows: 6, maxRows: 22 }"
                  placeholder="原文内容"
                />
                <div class="edit-row">
                  <n-select
                    v-model:value="draftType"
                    size="small"
                    class="f-select"
                    :options="TYPE_OPTIONS"
                  />
                  <n-button size="small" type="primary" :loading="saving" @click="saveContent">
                    保存修订
                  </n-button>
                  <n-button size="small" quaternary @click="editing = false">取消</n-button>
                </div>
              </template>
              <pre v-else class="content">{{ detail.raw_content }}</pre>
            </section>

            <section class="block">
              <div class="block-head">
                <OriginBadge kind="derived" />
              </div>
              <div class="derived-actions">
                <n-button size="small" @click="generate">生成知识</n-button>
                <n-button
                  v-if="detail.status === 'failed' || detail.status === 'raw'"
                  size="small"
                  @click="retryPipeline"
                >
                  重试入图（转 indexed）
                </n-button>
              </div>
              <p v-if="detail.error" class="fail-reason">失败原因：{{ detail.error }}</p>
              <div v-if="refs.length" class="ref-list">
                <button
                  v-for="ref in refs"
                  :key="ref"
                  class="ref-item"
                  type="button"
                  @click="gotoNode(ref)"
                >
                  {{ ref }}
                </button>
              </div>
              <p v-else class="empty-line">该事件尚未派生出知识节点。</p>
            </section>
          </template>

          <template v-if="detail" #actions>
            <n-button size="small" type="error" ghost @click="askDelete">删除事件</n-button>
          </template>
        </DetailPanel>
      </div>
    </div>

    <ConfirmDialog
      v-model:show="deleteOpen"
      danger
      title="删除这条事件原文？"
      :message="selectedId"
      :impacts="[
        '删除前会先留档到回收站（维护区「回收站」页可恢复）。',
        '若该事件是某个知识节点唯一的有效源证，后端会拒绝删除并指出是哪个节点。',
      ]"
      confirm-text="删除"
      :loading="deleting"
      @confirm="doDelete"
    />

    <ConfirmDialog
      v-model:show="activateOpen"
      title="需要切换活动书目"
      message="写操作只作用于活动书目"
      :impacts="activateImpacts"
      confirm-text="切换并继续"
      :loading="activating"
      @confirm="confirmActivate"
    />

    <n-modal :show="createOpen" @update:show="(v: boolean) => (createOpen = v)">
      <div class="create-box">
        <h3 class="create-title">新建事件（写入原文）</h3>
        <n-input
          v-model:value="createContent"
          type="textarea"
          :autosize="{ minRows: 5, maxRows: 16 }"
          placeholder="原文内容。以 ^ 开头的英文指令会走指令通道（例如 ^help）。"
        />
        <p v-if="scope.isJoint.value" class="warn-note">
          当前勾选了多本书目（联查 · 只读聚合）：新建事件只作用于活动书目《{{
            write.activeRepoName.value
          }}》，不会写进联查的其它库。
        </p>
        <div class="edit-row">
          <n-select v-model:value="createType" size="small" class="f-select" :options="TYPE_OPTIONS" />
          <span class="scope-note">写入书目：{{ createTargetName }}</span>
        </div>
        <div class="create-actions">
          <n-button size="small" quaternary @click="createOpen = false">取消</n-button>
          <n-button size="small" type="primary" :loading="creating" @click="doCreate">提交</n-button>
        </div>
      </div>
    </n-modal>
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 信息列表（查阅区）：查原文、修订原文、看衍生关联。
 *
 * 关键区分（P3）：详情分成**原文区**（标注「仅人类可修订」，编辑入口只对人工开放，
 * 界面上不存在任何 AI 改写原文的通道）与**衍生区**（关联节点 / 生成知识 / 状态重试）。
 *
 * 行为要求：真分页（服务端 offset）· 三态互斥 · 跨书目写入前显式切换活动书目。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NInput, NModal, NSelect, useMessage } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { TableColumn } from '@/components/ui/DataTable.vue'
import DetailPanel from '@/components/ui/DetailPanel.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import OriginBadge from '@/components/ui/OriginBadge.vue'
import * as eventsApi from '@/api/events'
import * as reposApi from '@/api/repos'
import type { EventDetailResponse, EventListItem } from '@/api/types'
import { useListPage } from '@/composables/useListPage'
import { useRepoScope } from '@/composables/useRepoScope'
import { useRepoWrite } from '@/composables/useRepoWrite'
import { useUnsavedGuard } from '@/composables/useUnsavedGuard'
import { useSessionStore } from '@/stores/session'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const session = useSessionStore()
const scope = useRepoScope()
const write = useRepoWrite()

const TYPE_OPTIONS = [
  { label: '交互 interaction', value: 'interaction' },
  { label: '数据 data', value: 'data' },
  { label: '来源 source', value: 'source' },
]
const STATUS_OPTIONS = [
  { label: '待处理 raw', value: 'raw' },
  { label: '已索引 indexed', value: 'indexed' },
  { label: '已入图 linked', value: 'linked' },
  { label: '失败 failed', value: 'failed' },
  { label: '已跳过 skipped', value: 'skipped' },
]

const list = useListPage<EventListItem, { status: string; type: string; query: string }>({
  initialFilters: { status: '', type: '', query: '' },
  pageSize: 20,
  fetch: (p) =>
    eventsApi.listEvents({
      status: p.filters.status || undefined,
      type: p.filters.type || undefined,
      query: p.filters.query || undefined,
      limit: p.limit,
      offset: p.offset,
      // 作用域参数唯一构造点：勾 1 本 → repo_id；勾 ≥2 本 → repo_ids（子集联查）
      ...scope.repoParams(),
    }),
})
const columns = computed<TableColumn[]>(() => {
  const base: TableColumn[] = [
    { key: 'event_type', label: '类型', width: 'sm' },
    { key: 'status', label: '状态', width: 'xs' },
    { key: 'raw_content', label: '原文（截断）', width: 'auto' },
    { key: 'created_at', label: '写入时间', width: 'md' },
  ]
  if (scope.isJoint.value) base.push({ key: 'repo_name', label: '来自书目', width: 'sm' })
  return base
})

// ── 详情 ──
const selectedId = ref(String(route.query.event ?? ''))
/** 选中条目所属书目（联查时用来判断写入是否需要先切活动书目） */
const selectedRepoId = ref('')
const detail = ref<EventDetailResponse | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const editing = ref(false)
const draftContent = ref('')
const draftType = ref('interaction')
const saving = ref(false)

const refs = computed(() => detail.value?.graph_refs ?? [])

async function loadDetail(eventId: string): Promise<void> {
  if (!eventId) {
    detail.value = null
    return
  }
  detailLoading.value = true
  detailError.value = ''
  try {
    // 详情读取只接受单库 `repo_id`（没有联查形态）：恰好勾 1 本时带它，否则缺省 = 活动书目
    detail.value = await eventsApi.getEvent(
      eventId,
      scope.effectiveRepoId.value || undefined,
    )
  } catch (e) {
    detail.value = null
    detailError.value = (e as Error).message
  } finally {
    detailLoading.value = false
  }
}

function onRowClick(row: EventListItem): void {
  selectedId.value = row.event_id
  selectedRepoId.value = row.repo_id ?? ''
  editing.value = false
  void router.replace({ query: { ...route.query, event: row.event_id } })
}

watch(selectedId, (id) => void loadDetail(id), { immediate: true })
// 切换勾选集合：列表与详情一起失效（`scopeKey` 是集合的稳定指纹）
watch(scope.scopeKey, () => {
  selectedId.value = ''
  void router.replace({ query: {} })
  void list.reload()
})

async function reloadAll(): Promise<void> {
  await list.reload()
  if (selectedId.value) await loadDetail(selectedId.value)
}

// ── 修订原文（人类通道）──
function startEdit(): void {
  if (!detail.value) return
  draftContent.value = detail.value.raw_content
  draftType.value = detail.value.event_type
  editing.value = true
}

/**
 * 修订草稿是否**脏**（离开守卫判据）：正在编辑 + 详情还在 + 内容**或类型**与原值不同。
 *
 * 类型也算：它与内容同属这一次修订（同一个「保存修订」按钮下发的两个字段），
 * 只比内容会让「只改了类型」的编辑静默丢失。
 * `detail !== null` 这一条的理由与图谱页相同：换库会把详情清空（编辑框随之消失），
 * 守卫只拦用户看得见的未保存编辑。
 */
const editDirty = computed(
  () =>
    editing.value &&
    detail.value !== null &&
    (draftContent.value !== detail.value.raw_content ||
      draftType.value !== detail.value.event_type),
)

useUnsavedGuard(
  () => editDirty.value,
  '原文修订还没保存，离开将丢弃这次修改。确定离开吗？',
)

async function saveContent(): Promise<void> {
  if (!detail.value) return
  const target = detail.value
  await runWithScope(selectedRepoId.value, async () => {
    saving.value = true
    try {
      await eventsApi.putEvent(target.event_id, {
        content: draftContent.value,
        event_type: draftType.value,
      })
      editing.value = false
      message.success('原文已修订')
      await session.commit()
      await reloadAll()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      saving.value = false
    }
  })
}

async function retryPipeline(): Promise<void> {
  if (!detail.value) return
  const target = detail.value
  await runWithScope(selectedRepoId.value, async () => {
    try {
      await eventsApi.putEventStatus(target.event_id, 'indexed')
      message.success('已请求重试入图')
      await session.commit()
      await reloadAll()
    } catch (e) {
      message.error((e as Error).message)
    }
  })
}

async function generate(): Promise<void> {
  const repoId = scope.effectiveRepoId.value
  if (!repoId) {
    message.warning('当前勾选了多本书目（联查）：生成知识只作用于活动书目，请只勾选一本再试')
    return
  }
  try {
    const res = await reposApi.generateRepo(repoId)
    message.success(res.message || '已入队生成知识')
    await session.commit()
    await reloadAll()
  } catch (e) {
    message.error((e as Error).message)
  }
}

function gotoNode(nodeId: string): void {
  void router.push({ name: 'graph', query: { node: nodeId } })
}

// ── 删除（二次确认 + 回收站说明）──
const deleteOpen = ref(false)
const deleting = ref(false)

function askDelete(): void {
  deleteOpen.value = true
}

async function doDelete(): Promise<void> {
  if (!selectedId.value) return
  const targetId = selectedId.value
  await runWithScope(selectedRepoId.value, async () => {
    deleting.value = true
    try {
      await eventsApi.deleteEvent(targetId)
      deleteOpen.value = false
      message.success('已删除，留档在回收站')
      selectedId.value = ''
      selectedRepoId.value = ''
      await router.replace({ query: {} })
      await session.commit()
      await list.reload()
    } catch (e) {
      deleteOpen.value = false
      message.error((e as Error).message)
    } finally {
      deleting.value = false
    }
  })
}

// ── 跨书目写入守卫 ──
const activateOpen = ref(false)
const activating = ref(false)
const activateImpacts = ref<string[]>([])
let pendingAction: (() => Promise<void>) | null = null

async function runWithScope(repoId: string | undefined, action: () => Promise<void>): Promise<void> {
  if (!write.needsActivation(repoId)) {
    await action()
    return
  }
  activateImpacts.value = write.activationImpacts(repoId as string)
  pendingAction = async () => {
    await write.activate(repoId as string)
    await action()
  }
  activateOpen.value = true
}

async function confirmActivate(): Promise<void> {
  activating.value = true
  try {
    await pendingAction?.()
    activateOpen.value = false
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    pendingAction = null
    activating.value = false
  }
}

// ── 新建事件 ──
const createOpen = ref(false)
const creating = ref(false)
const createContent = ref('')
const createType = ref('interaction')

/**
 * 写入目标 = 下面请求真正会打到的库：恰好勾 1 本 → 就是它；
 * 勾了多本（联查）→ 请求不带 `repo_id`，后端缺省 = **活动书目**。
 */
const createTargetRepoId = computed(() => scope.effectiveRepoId.value)
/** 与 `createTargetRepoId` **同源**：标签不许再写「活动书目」而请求打到顶栏勾选的那本书 */
const createTargetName = computed(() =>
  scope.effectiveRepoId.value
    ? `书目《${scope.repo.nameOf(scope.effectiveRepoId.value)}》`
    : `活动书目《${write.activeRepoName.value}》`,
)

/** 新建事件的常驻结果（刷新前一直可见）：指令与未确认写入都不许只闪一条绿色 toast */
interface CreateResult {
  title: string
  hint: string
  detail: string
  error: string
}

const createResult = ref<CreateResult | null>(null)

function openCreate(): void {
  createContent.value = ''
  createType.value = 'interaction'
  createOpen.value = true
}

async function doCreate(): Promise<void> {
  const content = createContent.value.trim()
  if (!content) {
    message.warning('内容不能为空')
    return
  }
  creating.value = true
  try {
    const res = await eventsApi.ingest(content, createType.value, createTargetRepoId.value)

    // ① 指令（^help / ^compress …）：**事件根本不落库**，绝不报「已写入」
    if (res.command_triggered) {
      createOpen.value = false
      const msg = res.message || '指令已执行'
      const rejected = msg.includes('未执行') || msg.includes('未生效')
      createResult.value = {
        title: rejected ? '指令未被接受（后端原文如下）' : '指令结果（未写入任何事件）',
        hint: '指令本身不落库（存储类指令除外）：后端返回 command_triggered=true 且 event_id 为空，这条内容没有进入时序事件存储。',
        detail: msg,
        error: '',
      }
      if (rejected) message.warning('指令未执行，原因见结果区', { duration: 6000 })
      else message.success('指令已执行')
      await session.commit()
      return
    }

    // ② 后端没回 event_id（例如版本过旧不认识该写入请求）：写入**未被确认**，同样不报「已写入」
    if (!res.event_id) {
      createResult.value = {
        title: '后端未返回事件 ID（写入未确认）',
        hint: '后端没回事件 ID，无法确认这条原文已落库——请先确认后端版本，不要凭「成功」提示重复提交。',
        detail: `status = ${res.status || '—'}，message = ${res.message || '—'}`,
        error: '后端版本可能过旧（不认识该写入请求），请重启后端服务后刷新页面。',
      }
      message.warning('后端未返回事件 ID，请检查后端版本')
      return
    }

    createResult.value = null
    message.success(res.message || `已写入（${res.status}）`)
    createOpen.value = false
    await session.commit()
    await list.reload()
  } catch (e) {
    message.error((e as Error).message)
  } finally {
    creating.value = false
  }
}

// ── 展示辅助 ──
const TYPE_TEXT: Record<string, string> = {
  interaction: '交互',
  data: '数据',
  source: '来源',
}
const STATUS_TEXT: Record<string, string> = {
  raw: '待处理',
  indexed: '已索引',
  linked: '已入图',
  failed: '失败',
  skipped: '已跳过',
}
const typeText = (v: string): string => TYPE_TEXT[v] ?? v
const statusText = (v: string): string => STATUS_TEXT[v] ?? v

/** 后端 created_at 是 **UTC** ISO 串（`event_store.py` 用 `datetime.now(timezone.utc).isoformat()`）：
 *  必须转成浏览器本地时间——早先只切字符串（`replace('T',' ')`）会让东八区用户看到「8 小时前」的写入时间。 */
function shortTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  // 无效值回退原样（宁可显示原文，也不渲染 Invalid Date）
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.split {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(360px, 1fr) minmax(360px, 1.05fr);
  gap: var(--dpim-space-3);
}
.split-list,
.split-detail {
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  overflow: hidden;
}
.f-select {
  width: 148px;
}
.f-input {
  width: 240px;
}
.scope-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  white-space: nowrap;
}
/* 联查态下的写动作警告（口径与 StorageCheckPage 的 warn-note 一致） */
.warn-note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-warning);
  line-height: 1.5;
}
.result-detail {
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
.tag,
.status {
  display: inline-block;
  padding: 1px var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  white-space: nowrap;
}
.tag {
  background: var(--dpim-surface-2);
  color: var(--dpim-text-2);
}
.tag--data {
  background: var(--dpim-info-soft);
  color: var(--dpim-info);
}
.tag--source {
  background: var(--dpim-origin-bg);
  color: var(--dpim-origin-fg);
}
.status--linked {
  background: var(--dpim-success-soft);
  color: var(--dpim-success);
}
.status--failed {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.status--raw {
  background: var(--dpim-warning-soft);
  color: var(--dpim-warning);
}
.status--indexed {
  background: var(--dpim-primary-soft);
  color: var(--dpim-primary);
}
.status--skipped {
  background: var(--dpim-surface-2);
  color: var(--dpim-text-3);
}
.preview {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--dpim-text-2);
  line-height: 1.5;
}
.time {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.block {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--dpim-space-2);
}
.content {
  margin: 0;
  padding: var(--dpim-space-3);
  background: var(--dpim-inset);
  box-shadow: var(--dpim-inset-shadow);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
  font-family: var(--dpim-font-sans);
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 40vh;
  overflow: auto;
}
.edit-row {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  flex-wrap: wrap;
}
.derived-actions {
  display: flex;
  gap: var(--dpim-space-2);
  flex-wrap: wrap;
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
.ref-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--dpim-space-2);
}
.ref-item {
  padding: 2px var(--dpim-space-2);
  border: var(--dpim-hairline) solid var(--dpim-derived-border);
  background: var(--dpim-derived-bg);
  color: var(--dpim-derived-fg);
  border-radius: var(--dpim-radius-pill);
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-xs);
  cursor: pointer;
}
.ref-item:hover {
  border-color: var(--dpim-primary);
}
.empty-line {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.create-box {
  width: min(560px, calc(100vw - var(--dpim-space-6)));
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-5);
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  box-shadow: var(--dpim-shadow);
}
.create-title {
  margin: 0;
  font-size: var(--dpim-fs-lg);
  font-weight: 600;
  color: var(--dpim-text);
}
.create-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--dpim-space-2);
}
</style>
