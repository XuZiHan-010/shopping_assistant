import { readdirSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'

import App from '@/App.vue'

import { routes } from './index'

function buildRouter() {
  return createRouter({ history: createWebHistory(), routes })
}

describe('路由表', () => {
  it('注册 / 与 /knowledge-base', () => {
    const router = buildRouter()

    expect(router.resolve('/').matched).not.toHaveLength(0)
    expect(router.resolve('/knowledge-base').matched).not.toHaveLength(0)
  })

  it('两条路由都能渲染', async () => {
    const router = buildRouter()
    const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })

    await router.push('/')
    await router.isReady()
    expect(wrapper.text()).toContain('Borough')

    await router.push('/knowledge-base')
    expect(wrapper.text()).toContain('知识库')
  })
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
