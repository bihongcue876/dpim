import { config } from '@vue/test-utils'
import naive from 'naive-ui'

config.global.plugins = [naive]

// jsdom lacks ResizeObserver — GraphCanvas needs it
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
} as any
