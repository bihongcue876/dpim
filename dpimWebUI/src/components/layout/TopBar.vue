<template>
  <header class="topbar">
    <div class="brand">
      <img class="brand-mark" src="/favicon.svg" alt="" aria-hidden="true" />
      <span class="brand-text">
        <span class="brand-name">DPIM</span>
        <span class="brand-sub">本地小图书馆</span>
      </span>
    </div>

    <RepoScopePicker class="topbar-scope" />

    <div class="topbar-right">
      <span class="chip" :class="health.connected ? 'chip--ok' : 'chip--bad'">
        {{ health.connected ? '后端已连接' : '后端未连接' }}
      </span>
      <span
        class="chip"
        :class="health.aiStatus === 'ready' ? 'chip--ok' : 'chip--warn'"
        :title="health.aiReason || health.aiStatusText"
      >
        {{ health.aiStatusText }}
      </span>
      <span v-if="health.queueDepth > 0" class="chip chip--info">
        队列 {{ health.queueDepth }}
      </span>
      <span class="chip chip--plain">v{{ health.version }}</span>

      <n-button quaternary size="small" :loading="refreshing" @click="refresh">
        刷新
      </n-button>
      <n-button
        quaternary
        size="small"
        :aria-label="theme.isDark ? '切换到亮色模式' : '切换到暗色模式'"
        :title="theme.isDark ? '切换到亮色模式' : '切换到暗色模式'"
        @click="theme.toggle()"
      >
        {{ theme.isDark ? '亮色' : '暗色' }}
      </n-button>
    </div>
  </header>
</template>

<script setup lang="ts">
/**
 * 顶栏（统一层）：品牌 · 全局书目选择器 · 状态徽章 · 刷新 · 主题切换。
 *
 * P1 可见性：连接状态、AI 降级、队列深度、版本都必须**常驻可见**——
 * 旧版这些信息只在「信息传入」页里可见，等于没有。
 *
 * 品牌标记直接用 `public/favicon.svg`（浏览器标签页同一个文件，单一来源，
 * 不另抄一份 SVG 以免两处漂移）；它是自带底色的整块图标，故不需要主题令牌着色。
 */
import { ref } from 'vue'
import { NButton } from 'naive-ui'
import RepoScopePicker from './RepoScopePicker.vue'
import { useHealthStore } from '@/stores/health'
import { useRepoStore } from '@/stores/repo'
import { useThemeStore } from '@/stores/theme'

const health = useHealthStore()
const repo = useRepoStore()
const theme = useThemeStore()

const refreshing = ref(false)

async function refresh(): Promise<void> {
  refreshing.value = true
  try {
    await Promise.all([repo.load(), health.refresh()])
  } finally {
    refreshing.value = false
  }
}
</script>

<style scoped>
.topbar {
  height: var(--dpim-topbar-h);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--dpim-space-4);
  padding: 0 var(--dpim-space-4);
  background: var(--dpim-surface);
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  flex-shrink: 0;
}
.brand-mark {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  display: block;
  border-radius: var(--dpim-radius-xs);
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.brand-name {
  font-size: var(--dpim-fs-base);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--dpim-text);
}
.brand-sub {
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
}
.topbar-scope {
  flex-shrink: 0;
}
.topbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  flex-wrap: nowrap;
  overflow: hidden;
}
.chip {
  padding: 3px var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  white-space: nowrap;
  border: var(--dpim-hairline) solid transparent;
}
.chip--ok {
  color: var(--dpim-success);
  background: var(--dpim-success-soft);
}
.chip--bad {
  color: var(--dpim-danger);
  background: var(--dpim-danger-soft);
}
.chip--warn {
  color: var(--dpim-warning);
  background: var(--dpim-warning-soft);
}
.chip--info {
  color: var(--dpim-info);
  background: var(--dpim-info-soft);
}
.chip--plain {
  color: var(--dpim-text-3);
  background: var(--dpim-surface-2);
}
</style>
