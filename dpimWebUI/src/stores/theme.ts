/**
 * 明暗双主题（store：theme）。
 *
 * 单一来源：`documentElement[data-dpim-mode]` → 全站 CSS 令牌翻转；
 * Naive UI 主题与 overrides 由本 store 一并给出（见 styles/naive-theme.ts）。
 * 偏好持久化在 localStorage `dpim_theme`，**仅在用户主动切换时写入**。
 */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { naiveThemeFor, overridesFor } from '@/styles/naive-theme'
import type { ThemeMode } from '@/styles/naive-theme'

const STORAGE_KEY = 'dpim_theme'

function readStoredMode(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {
    /* 隐私模式 */
  }
  return 'dark'
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readStoredMode())

  const naiveTheme = computed(() => naiveThemeFor(mode.value))
  const themeOverrides = computed(() => overridesFor(mode.value))
  const isDark = computed(() => mode.value === 'dark')

  /** DOM 同步：任何模式变化都写 dataset（含初始一次） */
  watch(
    mode,
    (m) => {
      document.documentElement.dataset.dpimMode = m
    },
    { immediate: true },
  )

  function toggle(): void {
    mode.value = mode.value === 'dark' ? 'light' : 'dark'
    try {
      localStorage.setItem(STORAGE_KEY, mode.value)
    } catch {
      /* 忽略 */
    }
  }

  return { mode, naiveTheme, themeOverrides, isDark, toggle }
})
