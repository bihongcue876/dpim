<template>
  <aside class="nav" :class="{ 'nav--collapsed': collapsed }">
    <nav class="nav-scroll" aria-label="主导航">
      <div v-for="zone in zones" :key="zone.key" class="nav-zone">
        <p class="nav-zone-title" :title="zone.basis">{{ zone.title }}</p>
        <RouterLink
          v-for="item in zone.items"
          :key="item.name"
          class="nav-item"
          :to="item.path"
          :title="item.desc"
        >
          <span class="nav-item-text">{{ item.title }}</span>
        </RouterLink>
      </div>
    </nav>
    <button class="nav-collapse" type="button" @click="toggle">
      {{ collapsed ? '»' : '«' }}
    </button>
  </aside>
</template>

<script setup lang="ts">
/**
 * 侧边栏分组导航（统一层）：四区（观测/查阅/写入/维护）+ 帮助。
 *
 * 折叠状态持久化在 localStorage `dpim_nav_collapsed`；折叠后只留图标位（这里以窄条呈现）。
 */
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import { NAV_ZONES } from '@/router/nav'

const KEY = 'dpim_nav_collapsed'

const collapsed = ref(readCollapsed())

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

function toggle(): void {
  collapsed.value = !collapsed.value
  try {
    localStorage.setItem(KEY, collapsed.value ? '1' : '0')
  } catch {
    /* 忽略 */
  }
}

const zones = NAV_ZONES
</script>

<style scoped>
.nav {
  position: relative;
  width: var(--dpim-nav-w);
  flex-shrink: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--dpim-surface);
  border-right: var(--dpim-hairline) solid var(--dpim-border);
  transition: width var(--dpim-dur) ease;
}
.nav--collapsed {
  width: 52px;
}
.nav-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--dpim-space-3) var(--dpim-space-2);
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-4);
}
.nav-zone {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-zone-title {
  margin: 0 0 var(--dpim-space-1);
  padding: 0 var(--dpim-space-2);
  font-size: var(--dpim-fs-xs);
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--dpim-text-3);
  white-space: nowrap;
  overflow: hidden;
}
.nav--collapsed .nav-zone-title {
  visibility: hidden;
  height: var(--dpim-space-3);
}
.nav-item {
  display: flex;
  align-items: center;
  height: 34px;
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-xs);
  color: var(--dpim-text-2);
  text-decoration: none;
  font-size: var(--dpim-fs-base);
  white-space: nowrap;
  overflow: hidden;
  transition: background-color var(--dpim-dur) ease, color var(--dpim-dur) ease;
}
.nav-item:hover {
  background: var(--dpim-surface-hover);
  color: var(--dpim-text);
}
.nav-item.router-link-active {
  background: var(--dpim-primary-soft);
  color: var(--dpim-primary);
  font-weight: 600;
  box-shadow: inset 2px 0 0 var(--dpim-primary);
}
.nav-item-text {
  overflow: hidden;
  text-overflow: ellipsis;
}
.nav--collapsed .nav-item-text {
  visibility: hidden;
}
.nav-collapse {
  flex-shrink: 0;
  height: 30px;
  border: none;
  border-top: var(--dpim-hairline) solid var(--dpim-border);
  background: transparent;
  color: var(--dpim-text-3);
  cursor: pointer;
  font-size: var(--dpim-fs-md);
}
.nav-collapse:hover {
  background: var(--dpim-surface-hover);
  color: var(--dpim-text);
}
</style>
