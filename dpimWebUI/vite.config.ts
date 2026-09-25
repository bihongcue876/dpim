import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 后端 API 端口可经环境变量覆盖（与启动脚本 start.bat / start.sh 联动），默认 8000
const API_PORT = process.env.DPIM_API_PORT || '8000'
const API_TARGET = `http://localhost:${API_PORT}`

// 代理路径清单：与后端 30 端点的前缀保持同步
const PROXY_PATHS = [
  '/health', '/agent', '/state-hash', '/ingest', '/events', '/nodes',
  '/query', '/feedback', '/settings', '/edges', '/graph', '/books', '/repos',
]

const proxy = Object.fromEntries(
  PROXY_PATHS.map((p) => [p, { target: API_TARGET, changeOrigin: true }]),
)

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})
