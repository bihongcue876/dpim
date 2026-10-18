import { config } from '@vue/test-utils'
import naive from 'naive-ui'

config.global.plugins = [naive]

// jsdom lacks ResizeObserver — GraphCanvas needs it
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
} as any

// jsdom lacks matchMedia — naive-ui 的虚拟列表（下拉面板）会读它，
// 缺了会在「打开下拉」时抛 `window.matchMedia is not a function`（链 AE 补）
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as any
}
