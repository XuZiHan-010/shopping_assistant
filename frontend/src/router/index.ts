import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import MerchantShell from '@/layouts/MerchantShell.vue'
import HomeView from '@/views/HomeView.vue'

/**
 * 商家工作台路由（W Task 5，设计说明 §4.1、PRD M1 与 §15「W」）。
 *
 * 所有业务页面都是外壳 `MerchantShell` 的子路由：侧栏 + 主视图 + 助手栏。
 * `/` 是首页（`HomeView`，Task 8 填实现）；运营助手不再是整页，而是常驻外壳、
 * 默认收起的助手栏 `AssistantRail`（W Task 6）。页面上的「问助手」直接调用
 * `useRailStore().ask()` 预填并打开助手栏，留在当前页，不再跳转。
 *
 * 旧地址：
 * - `/today` → `/`：今日简报并入首页；
 * - `/ops-assistant` → `/?assistant=open`：回到首页并打开助手栏（裁定 A，外壳读取
 *   该参数后打开助手栏，再只从地址里去掉 `assistant`）。这条记录保留路由名
 *   `assistant`：记忆页「来源对话」等链接（`{ name: 'assistant', query: { conversation } }`）
 *   因此仍能打开那段对话，其余查询参数原样保留。
 *
 * v1 后端（`graph.py` 冻结基线与 v1 `POST /api/chat`）不受影响，继续作为评测基线。
 *
 * **不创建 `/login`**：商家身份来自演示 Token 白名单，真实 SSO 属于 P2
 * （前端方案 §7.2、§11）。未知路径回到首页，因此 `/login` 会落到 `not-found`
 * 兜底——`index.spec.ts` 对此有显式断言。
 */
export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'shell',
    component: MerchantShell,
    children: [
      // —— 工作区 ——
      { path: '', name: 'home', component: HomeView },
      { path: 'catalog', name: 'catalog', component: () => import('@/views/CatalogView.vue') },
      { path: 'orders', name: 'orders', component: () => import('@/views/OrdersView.vue') },
      {
        path: 'inventory',
        name: 'inventory',
        component: () => import('@/views/InventoryView.vue'),
      },
      // —— 运营 ——
      {
        path: 'approvals',
        name: 'approval-list',
        component: () => import('@/views/ApprovalListView.vue'),
      },
      {
        path: 'approvals/:draftId',
        name: 'approval',
        component: () => import('@/views/ApprovalView.vue'),
        props: true,
      },
      {
        path: 'after-sales',
        name: 'after-sales',
        component: () => import('@/views/AfterSalesView.vue'),
      },
      {
        path: 'customer-signals',
        name: 'customer-signals',
        component: () => import('@/views/SignalsView.vue'),
      },
      {
        path: 'memories',
        name: 'merchant-memory',
        component: () => import('@/views/MerchantMemoryView.vue'),
      },
      // —— 管理（进入须管理员令牌，页面内用 `AdminGate` 包裹：无令牌只显示令牌入口、不发 /api/admin/* 请求；N5 的 `OpsStatusView` 同组追加） ——
      {
        path: 'knowledge-base',
        name: 'knowledge-base',
        component: () => import('@/views/KnowledgeBaseView.vue'),
      },
    ],
  },
  {
    path: '/today',
    name: 'today',
    redirect: { name: 'home' },
  },
  {
    path: '/ops-assistant',
    name: 'assistant',
    redirect: (to) => ({ name: 'home', query: { ...to.query, assistant: 'open' } }),
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    redirect: { name: 'home' },
  },
]

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

export default router
