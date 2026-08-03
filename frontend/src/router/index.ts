import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import AssistantView from '@/views/AssistantView.vue'

/**
 * F0 只注册两条路由。
 *
 * **不创建 `/login`**：MVP 与 P1 都没有登录页，商家身份来自演示 Token 白名单，
 * 真实 SSO 属于 P2（前端方案 §7.2、§11）。未知路径回到助手入口，因此
 * `/login` 会落到 `not-found` 兜底——`index.spec.ts` 对此有显式断言。
 */
export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'assistant',
    component: AssistantView,
  },
  {
    path: '/knowledge-base',
    name: 'knowledge-base',
    // 占位页用最终文件名，F8 在同一文件填实现，不留下待改名的临时文件。
    component: () => import('@/views/KnowledgeBaseView.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    redirect: { name: 'assistant' },
  },
]

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

export default router
