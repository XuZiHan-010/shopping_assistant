import { createPinia } from 'pinia'
import { createApp } from 'vue'

import '@/assets/styles.css'
import { i18n } from '@/i18n'
import { setCredentialProvider, setLocaleProvider } from '@/api/credentials'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useLocaleStore } from '@/stores/locale'
import App from './App.vue'
import router from './router'

const pinia = createPinia()
const app = createApp(App)

app.use(pinia)
app.use(i18n)

// 在挂载前同步完成，让首帧渲染就是恢复后的语言，不会先闪一下默认中文再
// 跳到英文——localStorage 读取是同步操作，不需要 await。
useLocaleStore(pinia).restore()

// 显式传 pinia 实例，不依赖隐式 active pinia——provider 在请求发出的任意时刻
// 都可能被调用，届时不一定处于 Vue 组件的 setup 上下文里，隐式 active pinia
// 拿不到。
setCredentialProvider(() => ({
  merchantToken: useAuthStore(pinia).selected?.token,
  // 管理员令牌只留在知识库后台页面的 Pinia 内存 store 里（Chat BI 看板与其
  // `useAnalyticsStore` 已随两页合并下线，2026-09-27）；transport 在请求瞬间
  // 取当前已授权页面持有的这一个。
  adminToken: useKnowledgeStore(pinia).adminToken,
  // v2 商家会话 ID，只在内存；由 `stores/auth.ts` 的 `openSession`/
  // `selectAndOpenSession` 写入，`buildAuthHeaders('merchant-session')` 在
  // 请求瞬间读取，本文件不缓存它。
  sessionId: useAuthStore(pinia).sessionId ?? undefined,
}))

// 与凭证同一模式：transport.ts / sse.ts 都不直接 import `useLocaleStore`，
// 只在请求瞬间调用这里注册的函数（前端方案 Task 11 Step 5）。
setLocaleProvider(() => useLocaleStore(pinia).locale)

app.use(router).mount('#app')
