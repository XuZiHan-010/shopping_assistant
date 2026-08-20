import { createPinia } from 'pinia'
import { createApp } from 'vue'

import '@/assets/styles.css'
import { setCredentialProvider } from '@/api/credentials'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeStore } from '@/stores/knowledge'
import App from './App.vue'
import router from './router'

const pinia = createPinia()
const app = createApp(App)

app.use(pinia)

// 显式传 pinia 实例，不依赖隐式 active pinia——provider 在请求发出的任意时刻
// 都可能被调用，届时不一定处于 Vue 组件的 setup 上下文里，隐式 active pinia
// 拿不到。
setCredentialProvider(() => ({
  merchantToken: useAuthStore(pinia).selected?.token,
  adminToken: useKnowledgeStore(pinia).adminToken,
}))

app.use(router).mount('#app')
