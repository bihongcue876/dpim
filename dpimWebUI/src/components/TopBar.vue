<template>
  <div class="topbar">
    <div class="topbar-left">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
          <rect x="3" y="3" width="18" height="8" rx="2" fill="#5b8cff" opacity="0.9"/>
          <rect x="3" y="13" width="18" height="8" rx="2" fill="#3fb68b" opacity="0.75"/>
        </svg>
      </span>
      <div class="brand-text">
        <span class="topbar-title">DPIM 控制台</span>
        <span class="topbar-sub">双区智能记忆</span>
      </div>
      <span class="key-badge" :class="keyStatus">
        <span class="key-dot"></span>{{ badgeText }}
      </span>
    </div>
    <div class="topbar-right">
      <button class="theme-toggle" :title="themeMode === 'dark' ? '切换到亮色模式' : '切换到暗色模式'"
        :aria-label="themeMode === 'dark' ? '切换到亮色模式' : '切换到暗色模式'" @click="$emit('toggle-theme')">
        <!-- 暗色时显示太阳（点击切到亮色）；亮色时显示月亮 -->
        <svg v-if="themeMode === 'dark'" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="12" cy="12" r="4"/>
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
        </svg>
        <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      </button>
      <n-button size="small" secondary :loading="loading" @click="$emit('refresh-key')">
        {{ loading ? '获取中' : '获取最新状态' }}
      </n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  keyStatus: 'unknown' | 'synced' | 'stale'
  loading: boolean
  themeMode?: 'dark' | 'light'
}>()

defineEmits<{ 'refresh-key': [], 'toggle-theme': [] }>()

// 供模板使用（无 props 使用告警则忽略）；默认暗色
const themeMode = computed(() => props.themeMode ?? 'dark')

const badgeText = computed(() => {
  if (props.keyStatus === 'unknown') return '待校验'
  if (props.keyStatus === 'synced') return '已同步'
  return '数据已变更'
})
const badgeClass = computed(() => props.keyStatus)
</script>

<style scoped>
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  height: 56px; padding: 0 20px;
  background: var(--dpim-surface, #161b22);
  border-bottom: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  flex-shrink: 0;
}
.topbar-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.brand-mark { display: inline-flex; align-items: center; flex-shrink: 0; }
.brand-text { display: flex; flex-direction: column; line-height: 1.1; }
.topbar-title { font-size: 16px; font-weight: 600; letter-spacing: 0.5px; color: var(--dpim-text, #e6edf3); }
.topbar-sub { font-size: 11px; color: var(--dpim-text-3, #7c8694); letter-spacing: 0.5px; margin-top: 2px; }
.key-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; padding: 3px 10px; border-radius: 999px;
  font-weight: 500; letter-spacing: 0.3px; margin-left: 4px;
  border: 1px solid transparent; white-space: nowrap;
}
.key-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.key-badge.unknown { background: rgba(242,201,76,0.12); color: #f2c94c; border-color: rgba(242,201,76,0.3); }
.key-badge.synced { background: rgba(63,182,139,0.12); color: #3fb68b; border-color: rgba(63,182,139,0.3); }
.key-badge.stale { background: rgba(240,128,128,0.12); color: #f08080; border-color: rgba(240,128,128,0.3); }
.topbar-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.theme-toggle {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 8px;
  border: 1px solid var(--dpim-border, rgba(255, 255, 255, 0.09));
  background: transparent; color: var(--dpim-text-2, #aab4c0);
  cursor: pointer; transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.theme-toggle:hover {
  color: var(--dpim-primary, #5b8cff);
  border-color: var(--dpim-primary, #5b8cff);
  background: var(--dpim-primary-soft, rgba(91, 140, 255, 0.14));
}
.theme-toggle:focus-visible {
  outline: 2px solid var(--dpim-primary, #5b8cff); outline-offset: 1px;
}
</style>
