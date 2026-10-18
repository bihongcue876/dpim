<template>
  <PageShell
    zone="维护"
    title="书目管理"
    description="管理这座图书馆的书目：书目 = 一本书（一 memory.db + 一 graph.json）；分组 = 书架"
  >
    <template #actions>
      <n-button type="primary" size="small" @click="openCreate">新建书目</n-button>
    </template>

    <!-- P6 失败可见：坏登记表不是「点了没反应」，而是页面顶部的错误原文 + 恢复出口 -->
    <SectionCard
      v-if="repo.error"
      title="书目登记表读取失败"
      hint="后端读 repos/index.json 失败（并进入只读锁存）；下方清单可能不可信。重建登记表是恢复出口。"
    >
      <p class="fail-text">{{ repo.error }}</p>
      <div class="inline-actions">
        <n-button size="small" @click="askRebuild">重建登记表</n-button>
        <n-button size="small" quaternary :loading="repo.loading" @click="reload">重试读取</n-button>
      </div>
    </SectionCard>

    <SectionCard v-if="pageError" title="上次操作失败" hint="后端返回的原文（点「关闭」前一直可见）。">
      <p class="fail-text">{{ pageError }}</p>
      <div class="inline-actions">
        <n-button size="small" quaternary @click="pageError = ''">关闭</n-button>
      </div>
    </SectionCard>

    <SectionCard v-if="notice" title="操作结果">
      <p class="notice-text">{{ notice }}</p>
      <div class="inline-actions">
        <n-button size="small" quaternary @click="notice = ''">关闭</n-button>
      </div>
    </SectionCard>

    <Toolbar>
      <n-input
        v-model:value="keyword"
        size="small"
        class="f-input"
        placeholder="筛选：名称 / 备注 / 分组 / 路径"
        clearable
      />
      <span class="scope-note">
        共 {{ repo.repos.length }} 本 · 当前显示 {{ filteredRepos.length }} 本
      </span>
      <span class="scope-note">「刷新修复」= 重载该库（坏文件走留档，不静默覆盖）</span>
      <template #right>
        <span class="scope-note">
          活动书目：{{ repo.activeRepo ? `《${repo.activeRepo.name}》` : '—' }}
        </span>
        <n-button size="small" quaternary :loading="repo.loading" @click="reload">刷新</n-button>
        <n-button size="small" @click="openAdopt">收养目录</n-button>
        <n-button size="small" @click="askRebuild">重建登记表</n-button>
      </template>
    </Toolbar>

    <!-- 滚动链：外层 min-height:0 + overflow:auto（否则卡片列表撑破页面） -->
    <div class="repos-scroll">
      <StateBlock v-if="showEmptyState && repo.loading" loading fixed-height />

      <StateBlock v-else-if="showEmptyState && repo.error" :error="repo.error" fixed-height>
        <template #retry>
          <n-button size="small" @click="reload">重试</n-button>
        </template>
      </StateBlock>

      <StateBlock
        v-else-if="showEmptyState"
        empty-text="尚无书目"
        hint="后端启动时会把现有数据登记为默认书目；也可以点右上角「新建书目」新建一本（托管 = 在数据根内建目录，外部 = 登记既有目录）。"
        fixed-height
      >
        <template #extra>
          <n-button size="small" type="primary" @click="openCreate">新建书目</n-button>
          <n-button size="small" @click="openAdopt">收养目录</n-button>
        </template>
      </StateBlock>

      <template v-else>
        <section v-for="group in filteredGroups" :key="group.name" class="shelf">
          <header class="shelf-head">
            <h3 class="shelf-title">书架 · {{ group.name }}</h3>
            <span class="shelf-count">{{ group.items.length }} 本</span>
          </header>

          <div class="cards">
            <article
              v-for="r in group.items"
              :key="r.repo_id"
              class="card"
              :class="{ 'card--active': r.active }"
            >
              <header class="card-head">
                <div class="card-head-text">
                  <h4 class="card-name">{{ r.name }}</h4>
                  <p class="card-note">{{ r.note || '（无备注）' }}</p>
                </div>
                <div class="badges">
                  <span v-if="r.active" class="badge badge--active">活动</span>
                  <span v-if="!r.managed" class="badge badge--dormant">休眠</span>
                  <span v-if="!r.loaded" class="badge badge--unloaded">未加载</span>
                  <span class="badge badge--kind">{{ kindText(r.root_kind) }}</span>
                </div>
              </header>

              <dl class="facts">
                <div class="fact">
                  <dt>分组</dt>
                  <dd>{{ r.group || '未分组' }}</dd>
                </div>
                <div class="fact">
                  <dt>事件 / 节点</dt>
                  <dd>{{ countText(r.total_events) }} / {{ countText(r.total_nodes) }}</dd>
                </div>
                <div class="fact">
                  <dt>书目 ID</dt>
                  <dd class="mono">{{ r.repo_id }}</dd>
                </div>
              </dl>

              <div class="paths">
                <div class="path-line">
                  <span class="path-label">db</span>
                  <code class="path">{{ r.db_path }}</code>
                </div>
                <div class="path-line">
                  <span class="path-label">json</span>
                  <code class="path">{{ r.json_path }}</code>
                </div>
              </div>

              <!-- v1.32：未加载原因（后端 RepoInfo.load_error；为空则不编造，只留下面的通用说明） -->
              <p v-if="r.load_error" class="load-error">未加载原因：{{ r.load_error }}</p>

              <p v-if="stateNote(r)" class="state-note">{{ stateNote(r) }}</p>

              <footer class="card-actions">
                <n-button size="tiny" @click="openEdit(r)">编辑</n-button>
                <n-button
                  size="tiny"
                  :disabled="r.root_kind !== 'external'"
                  @click="openRepoint(r)"
                >
                  重指向
                </n-button>
                <n-button
                  size="tiny"
                  :disabled="!!activateBlock(r)"
                  :loading="busyAction === `activate:${r.repo_id}`"
                  @click="doActivate(r)"
                >
                  设为活动书目
                </n-button>
                <n-button
                  size="tiny"
                  :disabled="!r.managed"
                  :loading="busyAction === `refresh:${r.repo_id}`"
                  @click="doRefresh(r)"
                >
                  刷新修复
                </n-button>
                <n-button
                  size="tiny"
                  type="error"
                  ghost
                  :disabled="!!removalBlock(r)"
                  @click="askRemove(r)"
                >
                  摘除登记
                </n-button>
                <n-button
                  size="tiny"
                  type="error"
                  ghost
                  :disabled="!!removalBlock(r)"
                  @click="askPurge(r)"
                >
                  删除书目及其文件
                </n-button>
              </footer>

              <p v-if="removalBlock(r)" class="block-reason">{{ removalBlock(r) }}</p>
            </article>
          </div>
        </section>
      </template>
    </div>

    <!-- ── 新建书目 ── -->
    <n-modal :show="createOpen" @update:show="(v: boolean) => (createOpen = v)">
      <div class="modal-box">
        <h3 class="modal-title">新建书目</h3>
        <p class="modal-hint">
          书目 = 一本书 = 一 memory.db + 一 graph.json；分组 = 书架。托管书目按分组落在数据根内的目录里。
        </p>
        <FieldRow label="名称" hint="1–80 字">
          <n-input v-model:value="createForm.name" size="small" placeholder="例如：地方志摘录" />
        </FieldRow>
        <FieldRow label="备注" hint="≤500 字；此前界面不显示备注，现在会显示在卡片上">
          <n-input
            v-model:value="createForm.note"
            type="textarea"
            size="small"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="可选"
          />
        </FieldRow>
        <FieldRow label="分组（书架）" hint="可选，留空归入「未分组」">
          <n-input v-model:value="createForm.group" size="small" placeholder="例如：地方资料" />
        </FieldRow>
        <FieldRow label="类型" hint="托管 = 新建目录；外部 = 登记既有目录（不移动文件）">
          <n-select
            v-model:value="createForm.root_kind"
            size="small"
            class="f-select"
            :options="KIND_OPTIONS"
          />
        </FieldRow>
        <FieldRow
          v-if="createForm.root_kind === 'external'"
          label="目录路径"
          hint="目录中须同时存在 memory.db 与 graph.json"
        >
          <n-input v-model:value="createForm.root" size="small" placeholder="例如 D:\资料\我的书目" />
        </FieldRow>
        <p v-if="modalError" class="fail-text">{{ modalError }}</p>
        <div class="modal-actions">
          <n-button size="small" quaternary @click="createOpen = false">取消</n-button>
          <n-button size="small" type="primary" :loading="creating" @click="doCreate">新建</n-button>
        </div>
      </div>
    </n-modal>

    <!-- ── 编辑书目 ── -->
    <n-modal :show="editOpen" @update:show="(v: boolean) => (editOpen = v)">
      <div class="modal-box">
        <h3 class="modal-title">编辑《{{ editRepo?.name }}》</h3>
        <FieldRow label="名称" hint="1–80 字">
          <n-input v-model:value="editForm.name" size="small" />
        </FieldRow>
        <FieldRow label="备注" hint="≤500 字">
          <n-input
            v-model:value="editForm.note"
            type="textarea"
            size="small"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="可选"
          />
        </FieldRow>
        <FieldRow
          label="分组（书架）"
          :hint="
            editRepo?.root_kind === 'external'
              ? '外部书目的分组只改清单里的书架归属'
              : '改分组会移动磁盘目录'
          "
        >
          <n-input v-model:value="editForm.group" size="small" placeholder="留空归入「未分组」" />
        </FieldRow>
        <FieldRow label="受管开关" hint="关闭 = 休眠：不加载、不检索、不构图（文件仍在磁盘上）">
          <n-switch v-model:value="editForm.managed" size="small" :disabled="isDefaultRepo" />
          <span class="scope-note">
            {{ editForm.managed ? '受管：会加载并参与检索与构图' : '休眠：清单里保留，但不参与任何读写' }}
          </span>
        </FieldRow>

        <p v-if="isDefaultRepo" class="modal-hint">
          默认书目是现役数据根，必须保持受管（开关已禁用）。
        </p>
        <p v-if="editWillMoveDir" class="warn-text">
          改分组会把这本书目的磁盘目录移动到新的书架目录（后端执行目录迁移，失败则登记回滚）。
        </p>
        <p v-else-if="editRepo?.root_kind === 'external'" class="modal-hint">
          外部书目的分组只改清单里的书架归属，不会移动磁盘目录（外部目录由你管理）。
        </p>
        <p v-if="editWillDormantActive" class="warn-text">
          该书目当前是活动书目；关闭受管后活动书目会回落到默认书目。
        </p>

        <p v-if="modalError" class="fail-text">{{ modalError }}</p>
        <div class="modal-actions">
          <n-button size="small" quaternary @click="editOpen = false">取消</n-button>
          <n-button size="small" type="primary" :loading="saving" @click="doSaveEdit">保存</n-button>
        </div>
      </div>
    </n-modal>

    <!-- ── 重指向（仅外部书目）── -->
    <n-modal :show="repointOpen" @update:show="(v: boolean) => (repointOpen = v)">
      <div class="modal-box">
        <h3 class="modal-title">重指向《{{ repointRepo?.name }}》的目录</h3>
        <p class="modal-hint">当前 db：<code class="path">{{ repointRepo?.db_path }}</code></p>
        <FieldRow label="新目录" hint="须同时存在 memory.db 与 graph.json">
          <n-input v-model:value="repointRoot" size="small" placeholder="新的目录绝对路径" />
        </FieldRow>
        <p class="modal-hint">
          换目录只改登记：原目录中的文件不会被移动或删除；新目录会被校验（禁设清单：磁盘根 / 用户主目录 /
          数据根之内 / 符号链接 / 已登记过的目录）。
        </p>
        <p v-if="modalError" class="fail-text">{{ modalError }}</p>
        <div class="modal-actions">
          <n-button size="small" quaternary @click="repointOpen = false">取消</n-button>
          <n-button size="small" type="primary" :loading="saving" @click="doRepoint">重指向</n-button>
        </div>
      </div>
    </n-modal>

    <!-- ── 收养目录（v1.32：目录里至少有一个库文件即可登记为外部书目）── -->
    <n-modal :show="adoptOpen" @update:show="(v: boolean) => (adoptOpen = v)">
      <div class="modal-box">
        <h3 class="modal-title">收养目录</h3>
        <p class="modal-hint">
          把磁盘上已有的书目目录登记进来：目录里 <strong>memory.db 与 graph.json 至少有一个</strong>即可
          （一个都没有请用「新建书目」）。登记为<strong>外部书目</strong>——DPIM 只登记与读写，不会移动该目录。
        </p>
        <FieldRow label="目录路径" hint="已存在的目录绝对路径（禁设清单照旧：磁盘根 / 用户主目录 / 数据根之内 / 符号链接）">
          <n-input
            v-model:value="adoptForm.root"
            size="small"
            class="f-mono"
            placeholder="例如 D:\资料\旧书目"
          />
        </FieldRow>
        <FieldRow label="名称" hint="1–80 字">
          <n-input v-model:value="adoptForm.name" size="small" placeholder="例如：旧书目（收养）" />
        </FieldRow>
        <FieldRow label="备注" hint="≤500 字">
          <n-input
            v-model:value="adoptForm.note"
            type="textarea"
            size="small"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="可选"
          />
        </FieldRow>
        <FieldRow label="分组（书架）" hint="可选，留空归入「未分组」">
          <n-input v-model:value="adoptForm.group" size="small" placeholder="例如：地方资料" />
        </FieldRow>
        <FieldRow label="缺失文件自动补空" hint="关闭则缺文件时直接失败，不补任何东西">
          <n-switch v-model:value="adoptForm.adopt_missing" size="small" />
          <span class="scope-note">
            {{ adoptForm.adopt_missing ? '缺哪个补哪个' : '只登记，缺文件就报错' }}
          </span>
        </FieldRow>
        <ul class="adopt-notes">
          <li><strong>只补空件，绝不覆盖</strong>目录里已存在的任何文件。</li>
          <li>两个文件都在时不会改动任何内容（后端回报的 created 为空）。</li>
          <li>
            缺 <code class="path">graph.json</code> 时会<strong>顺带尝试从图层操作日志（graph_ops）重放恢复图层</strong>——
            图层文件丢了但操作日志还在，收养就能把图层找回来。
          </li>
          <li>该目录已登记过 → 后端返回 409，不会重复登记。</li>
        </ul>
        <p v-if="modalError" class="fail-text">{{ modalError }}</p>
        <div class="modal-actions">
          <n-button size="small" quaternary @click="adoptOpen = false">取消</n-button>
          <n-button size="small" type="primary" :loading="adopting" @click="doAdopt">
            收养并登记
          </n-button>
        </div>
      </div>
    </n-modal>

    <ConfirmDialog
      v-model:show="showConfirm"
      :danger="confirmDanger"
      :title="confirmTitle"
      :message="confirmMessage"
      :impacts="confirmImpacts"
      :confirm-text="confirmText"
      :loading="confirming"
      @confirm="runConfirm"
      @cancel="confirmRepo = null"
    />
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 书目管理（维护区，规约 §4.8）：管理这座图书馆的书目与书架。
 *
 * 用户诉求「书目信息要能手工新建 / 增删改，全部修复」落到这张页上：
 * - 卡片补齐**备注**与 **db / json 两个路径**（此前界面完全看不到）；
 * - 6 个动作（编辑 / 重指向 / 设为活动 / 刷新修复 / 摘除登记 / 删除书目及其文件）
 *   全部有可见的禁用原因，不允许「点了没反应还提示成功」（P6）；
 * - 危险动作一律走 `ConfirmDialog`，逐条列出影响；
 * - 坏登记表的出路（重建登记表）在页面顶部显式提供。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { NButton, NInput, NModal, NSelect, NSwitch, useMessage } from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import FieldRow from '@/components/ui/FieldRow.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import * as reposApi from '@/api/repos'
import type { RepoInfo } from '@/api/types'
import { useRepoStore } from '@/stores/repo'
import { useSessionStore } from '@/stores/session'

const message = useMessage()
const repo = useRepoStore()
const session = useSessionStore()

/** 默认书目（现役数据根）：后端拒绝摘除 / 清除 / 休眠，界面必须同步禁并说明原因 */
const DEFAULT_REPO_ID = 'rp_default'

const KIND_OPTIONS = [
  { label: '托管 managed（在数据根内新建目录）', value: 'managed' },
  { label: '外部 external（登记既有目录）', value: 'external' },
]

const keyword = ref('')
const pageError = ref('')
const notice = ref('')
const busyAction = ref('')

function setNotice(text: string): void {
  notice.value = text
}

async function runAction(key: string, label: string, fn: () => Promise<void>): Promise<boolean> {
  busyAction.value = key
  pageError.value = ''
  try {
    await fn()
    return true
  } catch (e) {
    // P6：失败原文常驻页面，不只在 toast 里一闪
    pageError.value = `${label}失败：${(e as Error).message}`
    message.error((e as Error).message)
    return false
  } finally {
    busyAction.value = ''
  }
}

async function reload(): Promise<void> {
  await repo.load()
  if (!repo.error) notice.value = ''
}

onMounted(() => {
  void repo.load()
})

// ── 清单（按书架分组 + 关键词筛选）────────────────────────────────────────
const filteredRepos = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return repo.repos
  return repo.repos.filter((r) =>
    [r.name, r.note, r.group ?? '', r.repo_id, r.db_path, r.json_path].some((v) =>
      (v ?? '').toLowerCase().includes(kw),
    ),
  )
})

/** 有筛选时才本地重分组；否则直接用 store 的分组（书架维度单一来源） */
const filteredGroups = computed(() => {
  if (!keyword.value.trim()) return repo.groups
  const map = new Map<string, RepoInfo[]>()
  for (const r of filteredRepos.value) {
    const key = r.group?.trim() || '未分组'
    const list = map.get(key) ?? []
    list.push(r)
    map.set(key, list)
  }
  return [...map.entries()]
    .map(([name, items]) => ({ name, items }))
    .sort((a, b) => {
      if (a.name === '未分组') return 1
      if (b.name === '未分组') return -1
      return a.name.localeCompare(b.name, 'zh')
    })
})

/** 三态互斥：有数据时不显示空态（规约 §5.8） */
const showEmptyState = computed(() => filteredGroups.value.length === 0)

function countText(value: number | null | undefined): string {
  return value === null || value === undefined ? '未加载' : String(value)
}

function kindText(kind: RepoInfo['root_kind']): string {
  return kind === 'managed' ? '托管' : '外部'
}

/** 状态徽章之外的可见说明（也是动作按钮被禁用的原因） */
function stateNote(r: RepoInfo): string {
  const notes: string[] = []
  if (!r.managed) {
    notes.push('休眠：不加载、不检索、不构图（文件仍在磁盘上）；「刷新修复」与「设为活动书目」因此不可用。')
  } else if (!r.loaded) {
    notes.push('未加载：读不到事件 / 节点计数，也不能设为活动书目；可点「刷新修复」尝试重新加载。')
  }
  notes.push(
    r.root_kind === 'managed'
      ? '托管书目：目录由系统管理（repos/<分组>/<书目 ID>/），不支持重指向。'
      : '外部书目：目录由你管理，DPIM 只登记与读写，不会移动或删除其中的文件。',
  )
  return notes.join(' ')
}

function activateBlock(r: RepoInfo): string {
  if (r.active) return '已是活动书目'
  if (!r.managed) return '休眠书目不能设为活动书目：请先在「编辑」里打开受管开关。'
  if (!r.loaded) return '该书目未加载，无法设为活动书目：请先点「刷新修复」。'
  return ''
}

/** 摘除登记 / 删除书目及其文件的禁用原因（默认库与活动库由后端拒绝） */
function removalBlock(r: RepoInfo): string {
  if (r.repo_id === DEFAULT_REPO_ID) {
    return '默认书目是现役数据根，后端拒绝摘除与清除（其余书目可操作）。'
  }
  if (r.active) {
    return '该书目是当前活动书目，后端拒绝摘除与清除；请先把别的书目设为活动书目。'
  }
  return ''
}

// ── 新建 ──────────────────────────────────────────────────────────────────
const createOpen = ref(false)
const creating = ref(false)
const modalError = ref('')
const createForm = reactive({
  name: '',
  note: '',
  group: '',
  root_kind: 'managed' as 'managed' | 'external',
  root: '',
})

function openCreate(): void {
  createForm.name = ''
  createForm.note = ''
  createForm.group = ''
  createForm.root_kind = 'managed'
  createForm.root = ''
  modalError.value = ''
  createOpen.value = true
}

async function doCreate(): Promise<void> {
  const name = createForm.name.trim()
  if (!name) {
    modalError.value = '名称不能为空'
    return
  }
  if (createForm.root_kind === 'external' && !createForm.root.trim()) {
    modalError.value = '外部书目必须提供已存在的目录路径'
    return
  }
  creating.value = true
  modalError.value = ''
  pageError.value = ''
  try {
    const res = await reposApi.createRepo({
      name,
      note: createForm.note.trim(),
      group: createForm.group.trim() || undefined,
      root_kind: createForm.root_kind,
      root: createForm.root_kind === 'external' ? createForm.root.trim() : undefined,
    })
    createOpen.value = false
    setNotice(
      `${res.message}。新书目默认不是活动书目；如要写入它，请在卡片上点「设为活动书目」。`,
    )
    message.success(res.message)
    await repo.load()
    await session.commit()
  } catch (e) {
    modalError.value = (e as Error).message
    pageError.value = `新建书目失败：${(e as Error).message}`
  } finally {
    creating.value = false
  }
}

// ── 编辑 ──────────────────────────────────────────────────────────────────
const editOpen = ref(false)
const saving = ref(false)
const editRepo = ref<RepoInfo | null>(null)
const editForm = reactive({ name: '', note: '', group: '', managed: true })

const isDefaultRepo = computed(() => editRepo.value?.repo_id === DEFAULT_REPO_ID)
const editWillMoveDir = computed(() => {
  const r = editRepo.value
  if (!r || r.root_kind !== 'managed') return false
  return editForm.group.trim() !== (r.group ?? '')
})
const editWillDormantActive = computed(
  () => !!editRepo.value?.active && !editForm.managed,
)

function openEdit(r: RepoInfo): void {
  editRepo.value = r
  editForm.name = r.name
  editForm.note = r.note
  editForm.group = r.group ?? ''
  editForm.managed = r.managed
  modalError.value = ''
  editOpen.value = true
}

async function doSaveEdit(): Promise<void> {
  const r = editRepo.value
  if (!r) return
  const name = editForm.name.trim()
  if (!name) {
    modalError.value = '名称不能为空'
    return
  }
  saving.value = true
  modalError.value = ''
  pageError.value = ''
  try {
    await reposApi.updateRepo(r.repo_id, {
      name,
      note: editForm.note.trim(),
      group: editForm.group.trim(),
      // 默认书目必须保持受管（后端对默认库忽略该字段）
      managed: isDefaultRepo.value ? undefined : editForm.managed,
    })
    editOpen.value = false
    setNotice(`《${name}》已更新${editWillMoveDir.value ? '（分组已改，磁盘目录已迁移）' : ''}。`)
    message.success('书目已更新')
    await repo.load()
    await session.commit()
  } catch (e) {
    modalError.value = (e as Error).message
    pageError.value = `编辑《${r.name}》失败：${(e as Error).message}`
  } finally {
    saving.value = false
  }
}

// ── 重指向（仅外部书目）──────────────────────────────────────────────────
const repointOpen = ref(false)
const repointRepo = ref<RepoInfo | null>(null)
const repointRoot = ref('')

function openRepoint(r: RepoInfo): void {
  repointRepo.value = r
  repointRoot.value = ''
  modalError.value = ''
  repointOpen.value = true
}

async function doRepoint(): Promise<void> {
  const r = repointRepo.value
  if (!r) return
  const root = repointRoot.value.trim()
  if (!root) {
    modalError.value = '新目录路径不能为空'
    return
  }
  saving.value = true
  modalError.value = ''
  pageError.value = ''
  try {
    await reposApi.updateRepo(r.repo_id, { root })
    repointOpen.value = false
    setNotice(`《${r.name}》已重指向：${root}（原目录中的文件未被移动或删除）。`)
    message.success('书目已重指向')
    await repo.load()
    await session.commit()
  } catch (e) {
    modalError.value = (e as Error).message
    pageError.value = `重指向《${r.name}》失败：${(e as Error).message}`
  } finally {
    saving.value = false
  }
}

// ── 收养目录（v1.32）────────────────────────────────────────────────────
const adoptOpen = ref(false)
const adopting = ref(false)
const adoptForm = reactive({
  root: '',
  name: '',
  note: '',
  group: '',
  adopt_missing: true,
})

function openAdopt(): void {
  adoptForm.root = ''
  adoptForm.name = ''
  adoptForm.note = ''
  adoptForm.group = ''
  adoptForm.adopt_missing = true
  modalError.value = ''
  adoptOpen.value = true
}

/** `created` 是后端实际补出来的文件名（空数组 = 两个文件都在，没动任何东西） */
function createdText(created: string[]): string {
  if (!created.length) return '目录里两个文件都在，未补任何文件。'
  return `实际补出：${created.join('、')}（只补空件，未覆盖任何已有文件）。`
}

async function doAdopt(): Promise<void> {
  const root = adoptForm.root.trim()
  const name = adoptForm.name.trim()
  if (!root) {
    modalError.value = '目录路径不能为空'
    return
  }
  if (!name) {
    modalError.value = '名称不能为空（1–80 字）'
    return
  }
  adopting.value = true
  modalError.value = ''
  pageError.value = ''
  try {
    // 端点：POST /repos/adopt（v1.32）——目录里至少有一个库文件即可登记为外部书目
    const res = await reposApi.adoptRepo(
      root,
      name,
      adoptForm.note.trim(),
      adoptForm.group.trim(),
      adoptForm.adopt_missing,
    )
    adoptOpen.value = false
    setNotice(`${res.message} ${createdText(res.created)}`)
    message.success('目录已收养并登记')
    await repo.load()
    await session.commit()
  } catch (e) {
    // 不吞：弹窗内提示 + 页面顶部常驻原文（与其它写动作同一口径）
    modalError.value = (e as Error).message
    pageError.value = `收养目录失败：${(e as Error).message}`
  } finally {
    adopting.value = false
  }
}

// ── 设为活动 / 刷新修复 ──────────────────────────────────────────────────
async function doActivate(r: RepoInfo): Promise<void> {
  const ok = await runAction(`activate:${r.repo_id}`, '设为活动书目', async () => {
    await repo.activate(r.repo_id)
    await session.commit()
    setNotice(`活动书目已切换为《${r.name}》；未指定书目的写入将落到它。`)
  })
  if (ok) message.success('活动书目已切换')
}

async function doRefresh(r: RepoInfo): Promise<void> {
  await runAction(`refresh:${r.repo_id}`, '刷新修复', async () => {
    const res = await reposApi.refreshRepo(r.repo_id)
    setNotice(
      `${res.message}（事件 ${res.events} / 节点 ${res.nodes} / 边 ${res.edges}，` +
        `源证对账变更 ${res.reconcile_changed} 条）`,
    )
    message.success('已刷新修复（坏文件走留档，不静默覆盖）')
    await repo.load()
    await session.commit()
  })
}

// ── 二次确认（摘除 / 清除 / 重建登记表）──────────────────────────────────
type ConfirmKind = 'rebuild' | 'remove' | 'purge'

const showConfirm = ref(false)
const confirming = ref(false)
const confirmKind = ref<ConfirmKind>('rebuild')
const confirmRepo = ref<RepoInfo | null>(null)

const confirmDanger = computed(() => confirmKind.value !== 'rebuild')
const confirmTitle = computed(() => {
  if (confirmKind.value === 'rebuild') return '重建书目登记表？'
  if (confirmKind.value === 'purge') return '删除书目及其文件？（不可逆）'
  return '摘除这本书目的登记？'
})
const confirmMessage = computed(() =>
  confirmRepo.value ? `${confirmRepo.value.name}（${confirmRepo.value.repo_id}）` : '',
)
const confirmText = computed(() => {
  if (confirmKind.value === 'rebuild') return '重建'
  if (confirmKind.value === 'purge') return '删除文件'
  return '摘除登记'
})
const confirmImpacts = computed<string[]>(() => {
  if (confirmKind.value === 'rebuild') {
    return [
      '清掉坏索引的只读锁存，扫描磁盘重建 repos/index.json 登记表。',
      '不会删除任何磁盘数据文件（只写登记表这一个文件）。',
      '受管书目的显示名 / 备注 / 分组只存在于登记表，磁盘上没有痕迹：能按路径对上的沿用旧记录，对不上的以目录名为显示名。',
      '新登记的库需重启服务或点「刷新修复」后才会加载。',
    ]
  }
  if (confirmKind.value === 'purge') {
    return [
      '受管书目：先整库备份（备份失败即中止，绝不在没有备份的情况下删数据），再删除 memory.db（含 -wal / -shm / .lock）与 graph.json（含 .bak*）。不可逆。',
      '外部书目：只摘除登记，不删除外部目录中的任何文件（也就不生成备份）。',
      '备份写在库目录的 backups/ 下，库目录本身保留（那份备份正是退路）。',
    ]
  }
  return [
    '只摘除登记表条目，不删除磁盘上的任何数据文件（memory.db / graph.json 都保留）。',
    '摘除后该书目不再出现在书目清单与联查里；如需重新登记，可用「新建书目 · 外部」指向原目录。',
  ]
})

function askRebuild(): void {
  confirmKind.value = 'rebuild'
  confirmRepo.value = null
  showConfirm.value = true
}

function askRemove(r: RepoInfo): void {
  confirmKind.value = 'remove'
  confirmRepo.value = r
  showConfirm.value = true
}

function askPurge(r: RepoInfo): void {
  confirmKind.value = 'purge'
  confirmRepo.value = r
  showConfirm.value = true
}

async function runConfirm(): Promise<void> {
  const kind = confirmKind.value
  const r = confirmRepo.value
  confirming.value = true
  try {
    if (kind === 'rebuild') await doRebuild()
    else if (kind === 'remove' && r) await doRemove(r)
    else if (kind === 'purge' && r) await doPurge(r)
  } finally {
    confirming.value = false
    // 无论成败都关闭确认框：失败原文要能被看见（它在页面顶部的 SectionCard 里）
    showConfirm.value = false
    confirmRepo.value = null
  }
}

async function doRebuild(): Promise<void> {
  await runAction('rebuild', '重建登记表', async () => {
    const res = await reposApi.rebuildRepos()
    setNotice(res.message)
    message.success(`登记表已重建：${res.repos} 个书目`)
    await repo.load()
    await session.commit()
  })
}

async function doRemove(r: RepoInfo): Promise<void> {
  await runAction(`remove:${r.repo_id}`, '摘除登记', async () => {
    const res = await reposApi.deleteRepo(r.repo_id)
    setNotice(`${res.message}：《${r.name}》的磁盘文件仍在 ${r.db_path}`)
    message.success('已摘除登记（磁盘文件保留）')
    await repo.load()
    await session.commit()
  })
}

async function doPurge(r: RepoInfo): Promise<void> {
  await runAction(`purge:${r.repo_id}`, '删除书目及其文件', async () => {
    const res = await reposApi.purgeRepo(r.repo_id)
    setNotice(`${res.message}${res.backup_path ? ` 备份目录：${res.backup_path}` : ''}`)
    message.success('书目已清除')
    await repo.load()
    await session.commit()
  })
}
</script>

<style scoped>
/* 滚动链：本层 min-height:0 + overflow:auto，卡片列表在此层内滚动 */
.repos-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-4);
}
.shelf {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
}
.shelf-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--dpim-space-3);
  padding: 0 var(--dpim-space-1);
}
.shelf-title {
  margin: 0;
  font-size: var(--dpim-fs-base);
  font-weight: 600;
  color: var(--dpim-text);
}
.shelf-count {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--dpim-space-3);
}
.card {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-4);
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  min-width: 0;
}
.card--active {
  border-color: var(--dpim-primary-border);
  background: var(--dpim-surface-2);
}
.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--dpim-space-2);
}
.card-head-text {
  min-width: 0;
}
.card-name {
  margin: 0;
  font-size: var(--dpim-fs-lg);
  font-weight: 600;
  color: var(--dpim-text);
  line-height: 1.3;
  word-break: break-word;
}
.card-note {
  margin: var(--dpim-space-1) 0 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  line-height: 1.5;
  word-break: break-word;
}
.badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--dpim-space-1);
  flex-shrink: 0;
}
.badge {
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  white-space: nowrap;
  border: var(--dpim-hairline) solid transparent;
}
.badge--active {
  background: var(--dpim-success-soft);
  color: var(--dpim-success);
}
.badge--dormant {
  background: var(--dpim-warning-soft);
  color: var(--dpim-warning);
}
.badge--unloaded {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.badge--kind {
  background: var(--dpim-surface-2);
  color: var(--dpim-text-2);
  border-color: var(--dpim-border);
}
.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--dpim-space-2) var(--dpim-space-3);
  margin: 0;
}
.fact {
  min-width: 0;
}
.fact dt {
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
  margin-bottom: var(--dpim-space-1);
}
.fact dd {
  margin: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
  word-break: break-all;
}
.fact dd.mono {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
}
.paths {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-inset);
  box-shadow: var(--dpim-inset-shadow);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
}
.path-line {
  display: flex;
  align-items: baseline;
  gap: var(--dpim-space-2);
  min-width: 0;
}
.path-label {
  flex-shrink: 0;
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  color: var(--dpim-text-3);
  text-transform: uppercase;
}
.path {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  word-break: break-all;
  user-select: text;
}
.state-note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.5;
}
/* v1.32：未加载的真实原因（后端 load_error），用危险色与其它失败提示同一口径 */
.load-error {
  margin: 0;
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
  border-radius: var(--dpim-radius-sm);
  font-size: var(--dpim-fs-sm);
  line-height: 1.5;
  word-break: break-word;
}
.adopt-notes {
  margin: 0;
  padding-left: var(--dpim-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  line-height: 1.55;
}
.f-mono {
  width: 100%;
}
.f-mono :deep(input) {
  font-family: var(--dpim-font-mono);
}
.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--dpim-space-2);
  margin-top: auto;
}
.block-reason {
  margin: 0;
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-warning-soft);
  color: var(--dpim-warning);
  border-radius: var(--dpim-radius-sm);
  font-size: var(--dpim-fs-sm);
  line-height: 1.5;
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
.warn-text {
  margin: 0;
  padding: var(--dpim-space-2) var(--dpim-space-3);
  background: var(--dpim-warning-soft);
  color: var(--dpim-warning);
  border-radius: var(--dpim-radius-sm);
  font-size: var(--dpim-fs-sm);
  line-height: 1.5;
}
.scope-note {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  white-space: nowrap;
}
.f-input {
  width: 280px;
}
.f-select {
  width: 280px;
}
.modal-box {
  width: min(600px, calc(100vw - var(--dpim-space-6)));
  max-height: calc(100vh - var(--dpim-space-6));
  overflow: auto;
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
