import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 后端 API 端口可经环境变量覆盖（与启动脚本 start.bat / start.sh 联动），默认 8000
const API_PORT = process.env.DPIM_API_PORT || '8000'
const API_TARGET = `http://localhost:${API_PORT}`

// 代理路径清单：**新增后端端点时必须同步这里**，否则 dev 下前端调不到（走 5173 会 404）。
// 与后端 45 端点的前缀保持同步（v1.37：`/edges` 已是读端点，前缀不变）。
const PROXY_PATHS = [
  '/health', '/agent', '/state-hash', '/ingest', '/events', '/nodes',
  '/query', '/feedback', '/settings', '/edges', '/graph', '/repos',
  '/maintenance', '/logs', '/trash',
]

const proxy = Object.fromEntries(
  PROXY_PATHS.map((p) => [p, { target: API_TARGET, changeOrigin: true }]),
)

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // 契约类型单一来源：直接指向仓库根的 share/protocol.ts（不再手抄一份）
      '@protocol': fileURLToPath(new URL('../share/protocol.ts', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy,
    // 允许读取项目根之外的 share/（契约文件）
    fs: { allow: ['..'] },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})
