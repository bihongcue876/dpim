<template>
  <n-config-provider :theme="darkTheme" :locale="zhCN" :date-locale="dateZhCN">
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
          <n-tab-pane name="config" tab="配置">
            <ConfigTab :health="healthData" :validate="validate" :on-committed="onCommitted" />
          </n-tab-pane>
          <n-tab-pane name="events" tab="信息列表">
            <EventListTab :validate="validate" :on-committed="onCommitted" />
          </n-tab-pane>
          <n-tab-pane name="graph" tab="信息图">
            <GraphTab :key-status="keyStatus" />
          </n-tab-pane>
          <n-tab-pane name="search" tab="检索">
            <SearchTab />
          </n-tab-pane>
        </n-tabs>
      </n-layout>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { darkTheme, zhCN, dateZhCN, createDiscreteApi } from 'naive-ui'
import TopBar from '@/components/TopBar.vue'
import StatusBar from '@/components/StatusBar.vue'
import ConfigTab from '@/components/ConfigTab.vue'
import EventListTab from '@/components/EventListTab.vue'
import GraphTab from '@/components/GraphTab.vue'
import SearchTab from '@/components/SearchTab.vue'
import { useStateKey } from '@/composables/useStateKey'
import * as api from '@/api/client'
import type { HealthResponse } from '@/api/client'

const { message } = createDiscreteApi(['message'])

// ── State Key ──
const { keyStatus, init, validate, onCommitted } = useStateKey()
const keyLoading = ref(false)
const activeTab = ref('config')

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
})
onUnmounted(() => clearInterval(healthTimer))
</script>

<style>
html, body, #app { margin: 0; padding: 0; height: 100%; overflow: hidden; }
.app-root { height: 100vh; display: flex; flex-direction: column; background: var(--n-color); }
.app-tabs {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
  padding: 0;
}
.app-tabs > .n-tabs-nav { flex-shrink: 0; padding: 0 16px; }
.app-tabs .n-tab-pane { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
.n-tabs { background: inherit !important; }
.n-tab-pane { background: inherit !important; }

/* 暗色滚动条 */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.25); }
</style>
