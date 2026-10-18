import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import App from './App.vue'
import { router } from './router'
import { setErrorReporter } from './api/http'
import { reportClientLog } from './api/logs'
import './styles/tokens.css'
import './styles/base.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(naive)

// P6 失败可见：所有请求失败都送进后端 frontend-*.log（本地可翻看），
// 不再只留一条 toast。注入而非 import，避免 http ←→ logs 循环依赖。
setErrorReporter((level, message, source) => {
  void reportClientLog(level, message, source)
})

// 未捕获异常同样留痕：前端崩了也要能在日志页看到
window.addEventListener('error', (e) => {
  void reportClientLog('error', e.message, 'window.error')
})
window.addEventListener('unhandledrejection', (e) => {
  void reportClientLog('error', String(e.reason), 'unhandledrejection')
})

app.mount('#app')
