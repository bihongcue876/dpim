<template>
  <n-config-provider :theme="darkTheme" :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <n-dialog-provider>
    <n-message-provider>
      <n-layout class="app-root">
        <TopBar :key-status="keyStatus" :loading="keyLoading" @refresh-key="onRefreshKey" />
        <StatusBar :health="healthData" :connected="connected" />
        <n-tabs
          v-model:value="activeTab"
          type="line"
          size="medium"
          class="app-tabs"
          :tabs-padding="16"
        >
          <n-tab-pane name="config" tab="配置" :display-directive="'show'">
            <ConfigTab :health="healthData" :validate="validate" :on-committed="onCommitted" />
          </n-tab-pane>
          <n-tab-pane name="events" tab="信息列表" :display-directive="'show'">
            <EventListTab :validate="validate" :on-committed="onCommitted" />
          </n-tab-pane>
          <n-tab-pane name="graph" tab="信息图" :display-directive="'show'">
            <GraphTab :key-status="keyStatus" />
          </n-tab-pane>
          <n-tab-pane name="search" tab="检索" :display-directive="'show'">
            <SearchTab />
          </n-tab-pane>
          <n-tab-pane name="ingest" tab="信息传入" :display-directive="'show'">
            <IngestTab />
          </n-tab-pane>
        </n-tabs>
      </n-layout>
    </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { darkTheme, zhCN, dateZhCN, createDiscreteApi } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import TopBar from '@/components/TopBar.vue'
import StatusBar from '@/components/StatusBar.vue'
import ConfigTab from '@/components/ConfigTab.vue'
import EventListTab from '@/components/EventListTab.vue'
import GraphTab from '@/components/GraphTab.vue'
import SearchTab from '@/components/SearchTab.vue'
import IngestTab from '@/components/IngestTab.vue'
import { useStateKey } from '@/composables/useStateKey'
import * as api from '@/api/client'
import type { HealthResponse } from '@/api/client'

const { message } = createDiscreteApi(['message'])

// ── 全局主题：暗色底 + 亮色字，统一配色 / 圆角 / 字体 / 表面层级 ──
const themeOverrides: GlobalThemeOverrides = {
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
</script>

<style>
/* ── 设计令牌（全局可复用） ── */
:root {
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
  --dpim-gap: 14px;
  --dpim-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
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
}
.app-root { height: 100vh; display: flex; flex-direction: column; background: var(--dpim-bg); }
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
  padding: 2px 20px 0;
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
::selection { background: rgba(91, 140, 255, 0.32); color: #fff; }

/* 暗色滚动条 */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 8px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.22); }

/* 键盘可达性的聚焦描边 */
:focus-visible { outline: 2px solid var(--dpim-primary); outline-offset: 1px; border-radius: 4px; }
</style>
