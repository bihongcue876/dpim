<template>
  <n-modal
    :show="show"
    :mask-closable="false"
    :auto-focus="false"
    transform-origin="center"
    @update:show="onUpdateShow"
  >
    <div class="confirm" role="dialog" aria-modal="true">
      <h3 class="confirm-title" :class="{ 'confirm-title--danger': danger }">{{ title }}</h3>
      <p v-if="message" class="confirm-message">{{ message }}</p>
      <ul v-if="impacts.length" class="confirm-impacts">
        <li v-for="(item, i) in impacts" :key="i">{{ item }}</li>
      </ul>
      <slot />
      <div class="confirm-actions">
        <n-button quaternary @click="cancel">{{ cancelText }}</n-button>
        <n-button :type="danger ? 'error' : 'primary'" :loading="loading" @click="emit('confirm')">
          {{ confirmText }}
        </n-button>
      </div>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
/**
 * 危险操作二次确认（统一层）：标题 + 影响说明清单 + 明确按钮文案。
 *
 * P6：危险操作必须说清**影响**（会移动哪个目录 / 会删哪些文件 / 不可逆），
 * 不允许只弹一句「确定吗」。
 */
import { NButton, NModal } from 'naive-ui'

withDefaults(
  defineProps<{
    show: boolean
    title: string
    message?: string
    /** 影响说明（逐条列出，例如「会移动磁盘目录」「不可逆」） */
    impacts?: string[]
    confirmText?: string
    cancelText?: string
    danger?: boolean
    loading?: boolean
  }>(),
  {
    message: '',
    impacts: () => [],
    confirmText: '确定',
    cancelText: '取消',
    danger: false,
    loading: false,
  },
)

const emit = defineEmits<{ 'update:show': [value: boolean]; confirm: []; cancel: [] }>()

function cancel(): void {
  emit('update:show', false)
  emit('cancel')
}

function onUpdateShow(value: boolean): void {
  emit('update:show', value)
}
</script>

<style scoped>
.confirm {
  width: min(460px, calc(100vw - var(--dpim-space-6)));
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-5);
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  box-shadow: var(--dpim-shadow);
}
.confirm-title {
  margin: 0;
  font-size: var(--dpim-fs-lg);
  font-weight: 600;
  color: var(--dpim-text);
}
.confirm-title--danger {
  color: var(--dpim-danger);
}
.confirm-message {
  margin: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text-2);
  line-height: 1.6;
  word-break: break-word;
}
.confirm-impacts {
  margin: 0;
  padding-left: var(--dpim-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text-2);
  line-height: 1.5;
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--dpim-space-2);
  margin-top: var(--dpim-space-2);
}
</style>
