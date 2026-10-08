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
  // 外壳挂载后会恢复演示商家（知识库等子页还会加载自己的数据）。不注入 Mock 传输层的话，
  // 这里会打真实 fetch：本地没有后端时表现为慢速失败，在全量并发跑测试、
  // 事件循环繁忙时足以顶穿 5s 用例超时（单独跑这个文件不受影响、复现不稳定）。
  beforeEach(() => {
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8000')
  })

  it('/ 是首页，挂在商家工作台外壳下；旧的 v1 看板路径不再存在', () => {
    const router = buildRouter()

    const home = router.resolve('/')
    expect(home.name).toBe('home')
    expect(home.matched).toHaveLength(2)
    expect(home.matched[0]?.name).toBe('shell')
    expect(router.resolve('/ops-dashboard').matched[0]?.name).toBe('not-found')
  })

  it('所有业务页面都是外壳的子路由', () => {
    const router = buildRouter()

    for (const path of [
      '/',
      '/catalog',
      '/orders',
      '/inventory',
      '/approvals',
      '/approvals/d-1',
      '/after-sales',
      '/customer-signals',
      '/memories',
      '/knowledge-base',
    ]) {
      const resolved = router.resolve(path)
      expect(resolved.matched[0]?.name, path).toBe('shell')
      expect(resolved.matched, path).toHaveLength(2)
    }
  })

  it('注册商品与订单页（W Task 9 填实现）', () => {
    const router = buildRouter()

    expect(router.resolve('/catalog').name).toBe('catalog')
    expect(router.resolve('/orders').name).toBe('orders')
  })

  it('/ops-assistant 旧地址重定向到首页并要求打开助手栏（W 裁定 A）', async () => {
    const router = buildRouter()

    await router.push('/ops-assistant')
    expect(router.currentRoute.value.name).toBe('home')
    expect(router.currentRoute.value.fullPath).toBe('/?assistant=open')
  })

  it('「问助手」类跳转（name: assistant）落到首页并保留来源会话参数', async () => {
    const router = buildRouter()

    await router.push({ name: 'assistant', query: { conversation: 'c-1' } })
    expect(router.currentRoute.value.name).toBe('home')
    expect(router.currentRoute.value.query).toEqual({ conversation: 'c-1', assistant: 'open' })
  })

  it('/today 旧地址重定向到首页（简报并入首页）', async () => {
    const router = buildRouter()

    await router.push('/today')
    expect(router.currentRoute.value.name).toBe('home')
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('注册草稿审批路由，并把路径参数 draftId 作为 props 传给组件', () => {
    const router = buildRouter()

    const resolved = router.resolve('/approvals/d-1')
    expect(resolved.name).toBe('approval')
    expect(resolved.params.draftId).toBe('d-1')
    expect(resolved.matched[1]?.props).toEqual({ default: true })
  })

  it('注册库存告警与商家记忆路由', () => {
    const router = buildRouter()

    expect(router.resolve('/inventory').name).toBe('inventory')
    expect(router.resolve('/memories').name).toBe('merchant-memory')
  })

  // 挂载完整 App 是全量套件里最重的用例之一；即使传输层已 Mock，全量并发跑
  // 测试时模块收集阶段的 CPU 争抢仍偶尔顶穿默认 5s 超时。加宽到 15s 只是给
  // 抖动留余量，不是掩盖真实变慢——单独跑这个文件通常 <300ms。
  it('外壳与子路由都能渲染', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = buildRouter()
    // 预先建立商家会话，外壳侧栏的商家切换器才有当前商家可显示。
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
    expect(wrapper.find('nav').exists()).toBe(true)
    // W Task 8：首页的 h1 是带商家名的问候语，页面区块以「首页」命名。
    expect(wrapper.get('main#main section[aria-label="首页"] h1').text()).toContain('Borough商家100')

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
