<template>
  <n-config-provider :theme="naiveTheme" :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <n-dialog-provider>
    <n-message-provider>
      <n-layout class="app-root">
        <TopBar :key-status="keyStatus" :loading="keyLoading" :theme-mode="themeModeForTopBar"
          @refresh-key="onRefreshKey" @toggle-theme="toggleTheme" />
        <StatusBar :health="healthData" :connected="connected" />
        <n-tabs
          v-model:value="activeTab"
          type="line"
          size="medium"
          class="app-tabs"
          :tabs-padding="28"
        >
          <n-tab-pane name="config" tab="配置" :display-directive="'show'">
            <ConfigTab :health="healthData" :validate="validate" :on-committed="onCommitted" />
          </n-tab-pane>
          <n-tab-pane name="events" tab="信息列表" :display-directive="'show'">
            <EventListTab :validate="validate" :on-committed="onCommitted" />
          </n-tab-pane>
          <n-tab-pane name="graph" tab="信息图谱" :display-directive="'show'">
            <GraphTab :key-status="keyStatus" />
          </n-tab-pane>
          <n-tab-pane name="search" tab="检索" :display-directive="'show'">
            <SearchTab />
          </n-tab-pane>
          <n-tab-pane name="ingest" tab="信息传入" :display-directive="'show'">
            <IngestTab />
          </n-tab-pane>
          <n-tab-pane name="help" tab="帮助" :display-directive="'show'">
            <HelpTab />
          </n-tab-pane>
        </n-tabs>
      </n-layout>
    </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { darkTheme, lightTheme, zhCN, dateZhCN, createDiscreteApi } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import TopBar from '@/components/TopBar.vue'
import StatusBar from '@/components/StatusBar.vue'
import ConfigTab from '@/components/ConfigTab.vue'
import EventListTab from '@/components/EventListTab.vue'
import GraphTab from '@/components/GraphTab.vue'
import SearchTab from '@/components/SearchTab.vue'
import IngestTab from '@/components/IngestTab.vue'
import HelpTab from '@/components/HelpTab.vue'
import { useStateKey } from '@/composables/useStateKey'
import * as api from '@/api/client'
import type { HealthResponse } from '@/api/client'

const { message } = createDiscreteApi(['message'])

// ── 全局主题：暗色 / 亮色双模式，切换持久化到 localStorage（dpim_theme）──
// 模式切换时同步 documentElement[data-dpim-mode]，全站 CSS 设计令牌随之翻转，
// Naive UI 主题与自绘样式（含 GraphCanvas 画布）共用同一来源。
type ThemeMode = 'dark' | 'light'

function readStoredMode(): ThemeMode {
  try {
    const v = localStorage.getItem('dpim_theme')
    if (v === 'light' || v === 'dark') return v
  } catch { /* ignore */ }
  return 'dark' // 默认沿用原暗色
}

const themeMode = ref<ThemeMode>('dark') // onMounted 读存储（SSR/测试安全）

const naiveTheme = computed(() => (themeMode.value === 'dark' ? darkTheme : lightTheme))

// 亮色模式下的品牌色：加深主色保证白底可读性（WCAG 对比度）
const overridesLight: GlobalThemeOverrides = {
  common: {
    primaryColor: '#3b6fe0',
    primaryColorHover: '#5480e8',
    primaryColorPressed: '#2f5dc4',
    primaryColorSuppl: '#3b6fe0',
    successColor: '#1e9e74',
    successColorHover: '#2cae83',
    successColorPressed: '#188a65',
    successColorSuppl: '#1e9e74',
    warningColor: '#c9950f',
    warningColorHover: '#d6a52a',
    warningColorPressed: '#b08409',
    errorColor: '#d95858',
    errorColorHover: '#e47171',
    errorColorPressed: '#c24646',
    infoColor: '#2b93dd',
    infoColorHover: '#4aa5e6',
    infoColorPressed: '#2181c6',
  },
  Dialog: { color: '#ffffff' },
}

// 暗色模式沿用原设计令牌
const overridesDark: GlobalThemeOverrides = {
  common: {
    primaryColor: '#5b8cff',
    primaryColorHover: '#749fff',
    primaryColorPressed: '#4a78e8',
    primaryColorSuppl: '#5b8cff',
    successColor: '#3fb68b',
    successColorHover: '#53c69e',
    successColorPressed: '#36a37d',
    successColorSuppl: '#3fb68b',
    warningColor: '#f2c94c',
    warningColorHover: '#f5d36e',
    warningColorPressed: '#d9b23a',
    errorColor: '#f08080',
    errorColorHover: '#f49898',
    errorColorPressed: '#d96a6a',
    infoColor: '#4cb5f5',
    infoColorHover: '#6ec3f7',
    infoColorPressed: '#3aa3e6',
    borderRadius: '8px',
    borderRadiusSmall: '5px',
    fontFamily: "'Inter','PingFang SC','Microsoft YaHei',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif",
    fontFamilyMono: "'Cascadia Code','JetBrains Mono',Consolas,'Courier New',monospace",
    bodyColor: '#0e1217',
    cardColor: '#161b22',
    modalColor: '#161b22',
    popoverColor: '#1c2230',
    inputColor: 'rgba(255,255,255,0.04)',
    actionColor: 'rgba(255,255,255,0.05)',
    borderColor: 'rgba(255,255,255,0.09)',
    dividerColor: 'rgba(255,255,255,0.09)',
    textColorBase: '#e6edf3',
    textColor1: '#e6edf3',
    textColor2: '#aab4c0',
    textColor3: '#7c8694',
    placeholderColor: '#5b6572',
  },
  Tabs: {
    tabTextColorLine: '#aab4c0',
    tabTextColorActiveLine: '#5b8cff',
    tabTextColorHoverLine: '#749fff',
    barColor: '#5b8cff',
    tabFontWeightActive: '600',
  },
  Card: { borderColor: 'rgba(255,255,255,0.08)' },
  Dialog: { color: '#1c2230' },
  Pagination: { itemBorderRadius: '6px' },
}

const themeOverrides = computed<GlobalThemeOverrides>(() =>
  themeMode.value === 'dark' ? overridesDark : overridesLight,
)

function toggleTheme() {
  themeMode.value = themeMode.value === 'dark' ? 'light' : 'dark'
  // 用户主动切换才写存储；immediate 触发的一次只同步 DOM，避免覆盖已存偏好
  try {
    localStorage.setItem('dpim_theme', themeMode.value)
  } catch { /* ignore */ }
}

function syncThemeDom(mode: ThemeMode) {
  document.documentElement.dataset.dpimMode = mode
}

watch(themeMode, (mode) => syncThemeDom(mode), { immediate: true })

// ── State Key ──
const { keyStatus, init, validate, onCommitted } = useStateKey()
const keyLoading = ref(false)
const activeTab = ref('config')

// 跨 Tab 导航事件处理函数（搜索→图谱）
const onFocusNode = ((_e: CustomEvent) => {
  activeTab.value = 'graph'
}) as EventListener

// 跨 Tab 导航事件处理函数（信息传入→信息列表）
const onFocusEvent = ((_e: CustomEvent) => {
  activeTab.value = 'events'
}) as EventListener

async function onRefreshKey() {
  keyLoading.value = true
  try {
    await onCommitted()
    message.success(`状态已同步 (${keyStatus.value})`)
  } catch { message.error('获取状态失败') }
  finally { keyLoading.value = false }
}

// ── Health ──
const connected = ref(true)
const healthData = ref<HealthResponse | null>(null)

async function loadHealth() {
  try {
    healthData.value = await api.getHealth()
    connected.value = true
  } catch {
    connected.value = false
  }
}

let healthTimer: ReturnType<typeof setInterval>
onMounted(async () => {
  themeMode.value = readStoredMode()
  await init()
  loadHealth()
  healthTimer = setInterval(loadHealth, 30000)
  window.addEventListener('dpim:focus-node', onFocusNode)
  window.addEventListener('dpim:focus-event', onFocusEvent)
})
onUnmounted(() => {
  clearInterval(healthTimer)
  window.removeEventListener('dpim:focus-node', onFocusNode)
  window.removeEventListener('dpim:focus-event', onFocusEvent)
})

// 主题模式供 TopBar 切换按钮使用
const themeModeForTopBar = computed(() => themeMode.value)
</script>

<style>
/* ── 设计令牌（全局可复用）：与 App.vue 主题模式同步，暗色为默认 ──
   切换在 documentElement[data-dpim-mode] 上，各组件通过 var() 自动跟随 */
:root, :root[data-dpim-mode='dark'] {
  --dpim-bg: #0e1217;
  --dpim-surface: #161b22;
  --dpim-surface-2: #1c2230;
  --dpim-surface-hover: rgba(255, 255, 255, 0.04);
  --dpim-border: rgba(255, 255, 255, 0.09);
  --dpim-border-strong: rgba(255, 255, 255, 0.16);
  --dpim-text: #e6edf3;
  --dpim-text-2: #aab4c0;
  --dpim-text-3: #7c8694;
  --dpim-primary: #5b8cff;
  --dpim-primary-soft: rgba(91, 140, 255, 0.14);
  --dpim-radius: 12px;
  --dpim-radius-sm: 8px;
  --dpim-gap: 16px;
  --dpim-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
  --dpim-scroll-thumb: rgba(255, 255, 255, 0.12);
  --dpim-scroll-thumb-hover: rgba(255, 255, 255, 0.22);
  --dpim-selection-bg: rgba(91, 140, 255, 0.32);
  --dpim-selection-text: #fff;
  --dpim-grid-dot: rgba(255, 255, 255, 0.05);
  --dpim-log-bg: rgba(0, 0, 0, 0.22);
  /* 暗色：内嵌槽位沿用下沉深色（bg 语义不变） */
  --dpim-inset: var(--dpim-bg);
  --dpim-inset-shadow: none;
}

:root[data-dpim-mode='light'] {
  --dpim-bg: #f6f8fa;
  --dpim-surface: #ffffff;
  --dpim-surface-2: #f6f8fa;
  --dpim-surface-hover: rgba(15, 23, 42, 0.04);
  --dpim-border: rgba(15, 23, 42, 0.08);
  --dpim-border-strong: rgba(15, 23, 42, 0.16);
  --dpim-text: #1a2233;
  --dpim-text-2: #3f4c63;
  --dpim-text-3: #6f7b91;
  --dpim-primary: #3b6fe0;
  --dpim-primary-soft: rgba(59, 111, 224, 0.12);
  --dpim-radius: 12px;
  --dpim-radius-sm: 8px;
  --dpim-gap: 16px;
  --dpim-shadow: 0 6px 20px rgba(15, 23, 42, 0.08);
  --dpim-scroll-thumb: rgba(15, 23, 42, 0.18);
  --dpim-scroll-thumb-hover: rgba(15, 23, 42, 0.3);
  --dpim-selection-bg: rgba(59, 111, 224, 0.2);
  --dpim-selection-text: inherit;
  --dpim-grid-dot: rgba(15, 23, 42, 0.06);
  --dpim-log-bg: rgba(15, 23, 42, 0.04);
  /* 亮色层级策略：内嵌槽位（结果卡/表格容器/原文框）= 白卡 + 轻阴影浮起，
     不做「灰板压白卡」；灰仅保留给页面底（bg）与微妙头部带（surface-2） */
  --dpim-inset: #ffffff;
  --dpim-inset-shadow: 0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.04);
}

/* 全局盒模型：让 height:100% + padding 与 flex 全高布局精确吻合，
   修复配置/检索/信息传入等页底部被裁切的问题 */
*, *::before, *::after { box-sizing: border-box; }

html, body, #app { margin: 0; padding: 0; height: 100%; overflow: hidden; }
body {
  background: var(--dpim-bg);
  color: var(--dpim-text);
  font-family: 'Inter', 'PingFang SC', 'Microsoft YaHei', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  transition: background-color 0.25s ease, color 0.25s ease;
}
.app-root { height: 100vh; display: flex; flex-direction: column; background: var(--dpim-bg) !important; }
/* n-layout 内部有 .n-layout-scroll-container 中间层（普通 block，height:100%），
   不转成 flex 容器的话，其子元素（TopBar/StatusBar/n-tabs）的 flex 约束全部失效，
   n-tabs 高度退回内容高度 → 页面底部大面积空白不贴底 */
.app-root > .n-layout-scroll-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 主内容标签页：flex 全高自适应（不硬编码高度），子元素 flex:1 + min-height:0 才能正确解析 */
.app-tabs {
  flex: 1;
  min-height: 0;
  display: flex; flex-direction: column; overflow: hidden;
  padding: 0;
}
/* Naive UI 内部链：n-tabs 根（即 .app-tabs 自身）→ n-tabs-nav → n-tabs-pane-wrapper → n-tab-pane
   全部需要 flex + min-height:0 约束，否则内容超高时被 overflow:hidden 裁切且内层滚动失效 */
.app-tabs > .n-tabs-nav {
  flex-shrink: 0;
  padding: 4px 28px 0;
  background: var(--dpim-surface);
  border-bottom: 1px solid var(--dpim-border);
}
.app-tabs .n-tabs-pane-wrapper {
  flex: 1;
  min-height: 0;
  display: flex; flex-direction: column; overflow: hidden;
}
.app-tabs .n-tab-pane { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.n-tabs { background: inherit !important; }

/* 选中文本配色 */
::selection { background: var(--dpim-selection-bg); color: var(--dpim-selection-text); }

/* 滚动条（暗亮两套令牌） */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--dpim-scroll-thumb); border-radius: 8px; }
::-webkit-scrollbar-thumb:hover { background: var(--dpim-scroll-thumb-hover); }

/* 键盘可达性的聚焦描边 */
:focus-visible { outline: 2px solid var(--dpim-primary); outline-offset: 1px; border-radius: 4px; }
</style>
