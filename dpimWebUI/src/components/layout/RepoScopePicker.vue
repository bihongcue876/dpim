<template>
  <div class="picker" :title="scope.scopeLabel.value">
    <span class="picker-label">书目</span>
    <n-select
      class="picker-select"
      size="small"
      multiple
      :value="repo.selectedIds"
      :options="options"
      :max-tag-count="1"
      :consistent-menu-width="false"
      :disabled="!repo.usableIds.length"
      :placeholder="repo.usableIds.length ? '勾选要联查的书目（至少一本）' : '没有已加载的书目'"
      @update:value="onUpdate"
    >
      <template #action>
        <div class="picker-actions">
          <n-button size="tiny" quaternary :disabled="!repo.usableIds.length" @click="onSelectAll">
            全选（{{ repo.usableIds.length }} 本）
          </n-button>
          <n-button size="tiny" quaternary :disabled="!repo.fallbackRepoId" @click="onClear">
            清空
          </n-button>
        </div>
      </template>
    </n-select>
    <span v-if="scope.isJoint.value" class="picker-note">联查 · 只读聚合</span>
  </div>
</template>

<script setup lang="ts">
/**
 * 全局书目选择器（统一层）——重设计最关键的修订之一。
 *
 * 书目是**全局上下文，不是页面**：全站跟随这一个选择器，
 * 取代旧版散落在 5 个标签页里各自为政的「库」下拉框。
 *
 * 作用域是**用户自己勾选的库子集**，不是「单库 / 全部」两态：
 * - 每项一个勾选框（`n-select multiple`，与顶栏既有外观一致），按书架分组；
 * - 勾 1 个 = 单库（写动作打它）；勾 ≥2 个 = 子集联查（只读聚合）；
 * - **至少勾 1 个**：取消最后一个会被拒绝并提示（不出现「0 个库」状态）；
 * - 「全选 / 清空」两个快捷操作在菜单底部（`#action` 槽）；
 * - 勾选集合持久化（store 负责），刷新后保持，失效的库回退活动书目并提示。
 *
 * 只有「受管且已加载」的库可勾选：联查端点对休眠/未加载的库直接 422，
 * 让它们点得动却打不通等于挖坑，故显式禁用并在标签上说明原因。
 */
import { computed, watch } from 'vue'
import { NButton, NSelect, useMessage } from 'naive-ui'
import type { SelectMixedOption } from 'naive-ui/es/select/src/interface'
import type { RepoInfo } from '@/api/types'
import { useRepoScope } from '@/composables/useRepoScope'
import { useRepoStore } from '@/stores/repo'

const repo = useRepoStore()
const scope = useRepoScope()
const message = useMessage()

/** 选项标签：不可勾选时写明原因（点得动却打不通是更坏的结果） */
function optionLabel(r: RepoInfo): string {
  if (!r.managed) return `${r.name}（休眠 · 不参与联查）`
  if (!r.loaded) return `${r.name}（未加载）`
  return r.name
}

const options = computed<SelectMixedOption[]>(() => {
  const list: SelectMixedOption[] = []
  for (const group of repo.groups) {
    list.push({
      type: 'group',
      label: `书架 · ${group.name}`,
      key: `group:${group.name}`,
      children: group.items.map((r) => ({
        label: optionLabel(r),
        value: r.repo_id,
        disabled: !(r.managed && r.loaded),
      })),
    })
  }
  return list
})

/**
 * 勾选变化：空集合（取消最后一个）**保持原选中**并提示——
 * 后端读路径要么单库 `repo_id`、要么联查 `repo_ids`，没有「0 个库」这种合法形态。
 */
function onUpdate(value: unknown): void {
  const ids = Array.isArray(value) ? value.map((item) => String(item)) : []
  if (!ids.length) {
    message.warning('至少要选一个书目：已保持原选中')
    return
  }
  if (!repo.setSelection(ids)) {
    message.warning('所选书目都不可用（休眠 / 未加载）：已保持原选中')
  }
}

function onSelectAll(): void {
  if (!repo.usableIds.length) return
  repo.selectAll()
}

/** 清空 = 至少留一本（回落到活动书目）：不存在「0 个库」状态 */
function onClear(): void {
  if (!repo.clearToFallback()) {
    message.warning('至少要选一个书目：当前没有已加载的书目')
    return
  }
  message.info(`至少要选一个书目：已保留《${repo.nameOf(repo.fallbackRepoId)}》`)
}

// 作用域被回退 / 剔除了失效的库（持久化集合里有已删/已卸载的库）：给一次可见提示
watch(
  () => repo.scopeNotice,
  (notice) => {
    if (!notice) return
    message.warning(notice)
    repo.clearScopeNotice()
  },
  { immediate: true },
)
</script>

<style scoped>
.picker {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  min-width: 0;
}
.picker-label {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  flex-shrink: 0;
}
.picker-select {
  width: 240px;
}
.picker-actions {
  display: flex;
  justify-content: space-between;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-1) var(--dpim-space-2);
  border-top: var(--dpim-hairline) solid var(--dpim-border);
}
.picker-note {
  padding: 2px var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  background: var(--dpim-info-soft);
  color: var(--dpim-info);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  white-space: nowrap;
}
</style>
