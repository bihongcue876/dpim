<template>
  <div class="app-shell">
    <TopBar />
    <div class="app-body">
      <NavSidebar />
      <main class="app-main">
        <!-- 常驻错误条（P6 失败可见）：书目清单读取失败 = 全站作用域失效。
             旧状：`repo.error` 只在书目管理页渲染，其余 11 页表现为「一本书都没有」——
             顶栏选择器空着、概览台写「书目总数 0 本」，用户看不到任何原因。 -->
        <div v-if="repo.error" class="shell-error">
          <span class="shell-error-text">
            书目清单读取失败（不是「没有书目」）：{{ repo.error }}
          </span>
          <n-button size="tiny" :loading="repo.loading" @click="reloadRepos">重试</n-button>
        </div>
        <RouterView v-slot="{ Component }">
          <component :is="Component" />
        </RouterView>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 应用外壳（统一层）：顶栏 + 侧边栏 + 路由出口。
 *
 * 跨页通信一律走 router 与 store——旧的 `window` 字符串事件（`dpim:focus-node`
 * 之类）已废弃：隐式契约难追踪，且无法在刷新后存活。
 */
import { onMounted, onUnmounted, watch } from 'vue'
import { RouterView } from 'vue-router'
import { NButton } from 'naive-ui'
import TopBar from './TopBar.vue'
import NavSidebar from './NavSidebar.vue'
import { useHealthStore } from '@/stores/health'
import { useRepoStore } from '@/stores/repo'
import { useSessionStore } from '@/stores/session'

const health = useHealthStore()
const repo = useRepoStore()
const session = useSessionStore()

onMounted(async () => {
  await repo.load()
  void session.validate().catch(() => undefined)
  health.start()
})

onUnmounted(() => {
  health.stop()
})

// 勾选集合变化后，健康口径（容量/计数）随之刷新
// （作用域是集合而非两态：用稳定指纹 `scopeKey` 当依赖，数组本身每次都是新对象）
watch(
  () => repo.scopeKey,
  () => {
    void health.refresh()
  },
)

/** 错误条上的重试：重取书目清单（`repo.load()` 内部自己收错误，绝不抛出） */
async function reloadRepos(): Promise<void> {
  await repo.load()
}
</script>

<style scoped>
/* 常驻错误条：贯穿内容区顶部的横幅，与页面左右内边距对齐（与既有 warn/error 条同一套令牌） */
.shell-error {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-2) var(--dpim-space-5);
  background: var(--dpim-danger-soft);
  border-bottom: var(--dpim-hairline) solid var(--dpim-danger);
}
.shell-error-text {
  flex: 1;
  min-width: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-danger);
  word-break: break-word;
}
</style>
