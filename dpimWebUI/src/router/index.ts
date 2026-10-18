/**
 * 路由（重设计 §7）：引入 vue-router，页面可深链、可分享、刷新不丢位置。
 *
 * 采用 **hash 模式**：本地实验项目由 `vite dev` 直接提供，hash 无需任何服务端
 * 回退配置，从 `dist/` 静态打开也能用；代价是 URL 带 `#/`，可接受。
 *
 * 页面一律懒加载：首屏只加载外壳与当前页。
 */
import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { titleOfRoute } from './nav'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/overview' },
  {
    path: '/overview',
    name: 'overview',
    component: () => import('@/pages/OverviewPage.vue'),
  },
  { path: '/logs', name: 'logs', component: () => import('@/pages/LogsPage.vue') },
  { path: '/storage', name: 'storage', component: () => import('@/pages/StorageCheckPage.vue') },
  { path: '/events', name: 'events', component: () => import('@/pages/EventsPage.vue') },
  { path: '/graph', name: 'graph', component: () => import('@/pages/GraphPage.vue') },
  { path: '/search', name: 'search', component: () => import('@/pages/SearchPage.vue') },
  { path: '/ingest', name: 'ingest', component: () => import('@/pages/IngestPage.vue') },
  { path: '/repos', name: 'repos', component: () => import('@/pages/ReposPage.vue') },
  { path: '/backup', name: 'backup', component: () => import('@/pages/BackupPage.vue') },
  { path: '/trash', name: 'trash', component: () => import('@/pages/TrashPage.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/pages/SettingsPage.vue') },
  { path: '/help', name: 'help', component: () => import('@/pages/HelpPage.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/overview' },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.afterEach((to) => {
  const title = titleOfRoute(to.name)
  document.title = title === 'DPIM' ? 'DPIM' : `${title} · DPIM`
})
