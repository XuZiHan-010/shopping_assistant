import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import OpsAssistantView from '@/views/OpsAssistantView.vue'

/**
 * F0 / P1 共注册路由：助手、知识库后台等。
 *
 * `/` 是运营助手页（`OpsAssistantView`）：两页合并评审（2026-09-26 评审，
 * 2026-09-27 用户裁定「选项 C」）结论是 v2 在导出、反馈、简报、审批、猜你想问、
 * 规则问答均已达到或超过 v1 分析助手，指标趋势可视化的唯一差距已补齐
 * （`MerchantChatResponse.visualization`，契约 §8.7.11），因此 v1 前端页面
 * `AssistantView.vue`/`OpsDashboardView.vue` 与其 Chat BI 组件下线；v1 后端
 * （`graph.py` 冻结基线与 v1 `POST /api/chat`）不受影响，继续作为评测基线保留
 * （`docs/PRD.md` §15 N2、`AGENTS.md` 既有约束）。
 *
 * **不创建 `/login`**：MVP 与 P1 都没有登录页，商家身份来自演示 Token 白名单，
 * 真实 SSO 属于 P2（前端方案 §7.2、§11）。未知路径回到助手入口，因此
 * `/login` 会落到 `not-found` 兜底——`index.spec.ts` 对此有显式断言。
 */
export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'assistant',
    component: OpsAssistantView,
  },
  {
    path: '/knowledge-base',
    name: 'knowledge-base',
    // 占位页用最终文件名，F8 在同一文件填实现，不留下待改名的临时文件。
    component: () => import('@/views/KnowledgeBaseView.vue'),
  },
  {
    path: '/approvals',
    name: 'approval-list',
    component: () => import('@/views/ApprovalListView.vue'),
  },
  {
    path: '/approvals/:draftId',
    name: 'approval',
    component: () => import('@/views/ApprovalView.vue'),
    props: true,
  },
  {
    path: '/inventory',
    name: 'inventory',
    component: () => import('@/views/InventoryView.vue'),
  },
  {
    path: '/after-sales',
    name: 'after-sales',
    component: () => import('@/views/AfterSalesView.vue'),
  },
  {
    path: '/customer-signals',
    name: 'customer-signals',
    component: () => import('@/views/SignalsView.vue'),
  },
  {
    path: '/today',
    name: 'today',
    component: () => import('@/views/TodayView.vue'),
  },
  {
    // 旧地址重定向：合并前 `/ops-assistant` 是 v2 助手的独立入口，合并后它就是 `/`。
    path: '/ops-assistant',
    redirect: { name: 'assistant' },
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
