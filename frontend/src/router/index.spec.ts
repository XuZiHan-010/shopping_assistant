import { readdirSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import App from '@/App.vue'
import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

import { routes } from './index'

function buildRouter() {
  return createRouter({ history: createWebHistory(), routes })
}

describe('路由表', () => {
  // OpsAssistantView 挂载后会加载 v2 会话目录。不注入 Mock 传输层的话，
  // 这里会打真实 fetch：本地没有后端时表现为慢速失败，在全量并发跑测试、
  // 事件循环繁忙时足以顶穿 5s 用例超时（单独跑这个文件不受影响、复现不稳定）。
  beforeEach(() => {
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8000')
  })

  it('注册助手与知识库入口；旧的 v1 看板路径不再存在', () => {
    const router = buildRouter()

    expect(router.resolve('/').matched[0]?.name).toBe('assistant')
    expect(router.resolve('/knowledge-base').matched).not.toHaveLength(0)
    expect(router.resolve('/ops-dashboard').matched[0]?.name).toBe('not-found')
  })

  it('/ops-assistant 旧地址重定向到 /（两页合并，2026-09-27 用户裁定「选项 C」）', async () => {
    const router = buildRouter()

    await router.push('/ops-assistant')
    expect(router.currentRoute.value.name).toBe('assistant')
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('注册草稿审批路由，并把路径参数 draftId 作为 props 传给组件', () => {
    const router = buildRouter()

    const resolved = router.resolve('/approvals/d-1')
    expect(resolved.matched[0]?.name).toBe('approval')
    expect(resolved.params.draftId).toBe('d-1')
  })

  it('注册库存告警与今日简报路由', () => {
    const router = buildRouter()

    expect(router.resolve('/inventory').matched[0]?.name).toBe('inventory')
    expect(router.resolve('/today').matched[0]?.name).toBe('today')
  })

  // 挂载完整 App 是全量套件里最重的用例之一；即使传输层已 Mock，全量并发跑
  // 测试时模块收集阶段的 CPU 争抢仍偶尔顶穿默认 5s 超时。加宽到 15s 只是给
  // 抖动留余量，不是掩盖真实变慢——单独跑这个文件通常 <300ms。
  it('两条路由都能渲染', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = buildRouter()
    // OpsAssistantView 需要已建立的商家会话才能正常渲染工作台标题
    // （`auth.selected`），否则只会看到未选商家的空态——与
    // `OpsAssistantView.spec.ts` 的 `mountOps()` 同一模式。
    const auth = useAuthStore()
    await auth.loadMerchants()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            session_id: 'sid'.padEnd(43, '0'),
            role: 'MERCHANT',
            expires_at: '2099-01-01T00:00:00Z',
            merchant_display_name: 'Borough商家100',
          }),
          { status: 201, headers: { 'content-type': 'application/json' } },
        ),
      ),
    )
    await auth.openSession(auth.merchants[0]!)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [], next_cursor: null, has_more: false }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    const wrapper = mount(App, { global: { plugins: [pinia, router, i18n] } })

    await router.push('/')
    await router.isReady()
    await flushPromises()
    expect(wrapper.text()).toContain('Borough')

    await router.push('/knowledge-base')
    expect(wrapper.text()).toContain('知识库')
  }, 15_000)
})

describe('MVP 不存在登录页', () => {
  // 原验收「/login 未注册」在有兜底路由时无法证明——兜底会吃掉它，
  // resolve('/login') 会匹配到 catch-all 而不是无匹配。改为下面三条可执行断言。

  it('路由表里没有任何 login 记录', () => {
    const suspicious = routes.filter(
      (route) =>
        route.path.toLowerCase().includes('login') ||
        String(route.name ?? '')
          .toLowerCase()
          .includes('login'),
    )

    expect(suspicious).toEqual([])
  })

  it('/login 解析到兜底路由而不是专门的登录路由', () => {
    const router = buildRouter()
    const matched = router.resolve('/login').matched

    expect(matched).toHaveLength(1)
    expect(matched[0]?.name).toBe('not-found')
  })

  it('views 目录下不存在 LoginView.vue', () => {
    // happy-dom 里 import.meta.url 不是 file:// scheme，从工作目录解析。
    const viewsDir = resolve(process.cwd(), 'src', 'views')

    expect(readdirSync(viewsDir)).not.toContain('LoginView.vue')
  })
})
