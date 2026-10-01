import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n } from '@/i18n'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'

import SideNav from './SideNav.vue'

const MERCHANTS = [
  { merchantId: 'm-100', displayName: 'Borough商家100', token: 't-100' },
  { merchantId: 'm-101', displayName: 'Borough商家101', token: 't-101' },
]

async function mountNav(path = '/') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.merchants = [...MERCHANTS]
  auth.selected = MERCHANTS[0]
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SideNav, {
    attachTo: document.body,
    global: { plugins: [pinia, i18n, router] },
  })
  return { wrapper, auth, router }
}

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
})

describe('SideNav 侧栏', () => {
  it('分四组：工作区、运营、运营助手、管理，条目与顺序固定', async () => {
    const { wrapper } = await mountNav()

    const groups = wrapper.findAll('[data-nav-group]')
    expect(groups.map((group) => group.attributes('data-nav-group'))).toEqual([
      'workspace',
      'operations',
      'assistant',
      'admin',
    ])

    const labelsOf = (key: string) =>
      wrapper
        .get(`[data-nav-group="${key}"]`)
        .findAll('[data-nav-item]')
        .map((item) => item.text().trim())
    expect(labelsOf('workspace')).toEqual(['首页', '商品', '订单', '库存'])
    expect(labelsOf('operations')).toEqual(['待审批', '售后', '顾客信号', '记忆'])
    expect(labelsOf('admin')).toEqual(['知识库'])
    wrapper.unmount()
  })

  it('链接指向对应路由', async () => {
    const { wrapper } = await mountNav()

    const hrefs = wrapper.findAll('a[data-nav-item]').map((link) => link.attributes('href'))
    expect(hrefs).toEqual([
      '/',
      '/catalog',
      '/orders',
      '/inventory',
      '/approvals',
      '/after-sales',
      '/customer-signals',
      '/memories',
      '/knowledge-base',
    ])
    wrapper.unmount()
  })

  it('侧栏不放「对话记录」', async () => {
    const { wrapper } = await mountNav()

    expect(wrapper.text()).not.toContain('对话记录')
    expect(wrapper.text()).not.toContain('历史会话')
    wrapper.unmount()
  })

  it('当前页的 aria-current 为 page，其余条目没有 aria-current', async () => {
    const { wrapper } = await mountNav('/inventory')

    const current = wrapper.findAll('[aria-current="page"]')
    expect(current).toHaveLength(1)
    expect(current[0]!.attributes('data-nav-item')).toBe('inventory')
    wrapper.unmount()
  })

  it('首页只在 / 时高亮，不因为嵌套路由共享前缀而常亮', async () => {
    const { wrapper } = await mountNav('/orders')

    expect(wrapper.get('[data-nav-item="home"]').attributes('aria-current')).toBeUndefined()
    expect(wrapper.get('[data-nav-item="orders"]').attributes('aria-current')).toBe('page')
    wrapper.unmount()
  })

  it('审批详情页高亮「待审批」', async () => {
    const { wrapper } = await mountNav('/approvals/d-1')

    expect(wrapper.get('[data-nav-item="approvals"]').attributes('aria-current')).toBe('page')
    wrapper.unmount()
  })

  it('路由变化后 aria-current 跟着移动', async () => {
    const { wrapper, router } = await mountNav('/')
    expect(wrapper.get('[data-nav-item="home"]').attributes('aria-current')).toBe('page')

    await router.push('/customer-signals')

    expect(wrapper.get('[data-nav-item="home"]').attributes('aria-current')).toBeUndefined()
    expect(wrapper.get('[data-nav-item="signals"]').attributes('aria-current')).toBe('page')
    wrapper.unmount()
  })

  it('运营助手是切换按钮：aria-pressed / aria-expanded 跟随助手栏开合，并声明控制助手栏', async () => {
    const { wrapper } = await mountNav()

    const assist = wrapper.get('[data-nav-group="assistant"] button')
    expect(assist.text()).toContain('运营助手')
    expect(assist.attributes('aria-pressed')).toBe('false')
    expect(assist.attributes('aria-expanded')).toBe('false')
    expect(assist.attributes('aria-controls')).toBe('assistant-rail')

    await assist.trigger('click')
    expect(wrapper.emitted('toggle-assistant')).toHaveLength(1)

    await wrapper.setProps({ assistantOpen: true })
    expect(assist.attributes('aria-pressed')).toBe('true')
    expect(assist.attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })

  it('商家切换沿用 MerchantSwitcher：显示当前商家，选另一个商家时改选', async () => {
    const { wrapper, auth } = await mountNav()
    const select = vi.spyOn(auth, 'selectByDisplayName')

    const trigger = wrapper.get('[data-testid="merchant-switcher"]')
    expect(trigger.text()).toContain('Borough商家100')

    await trigger.trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')

    expect(select).toHaveBeenCalledWith('Borough商家101')
    wrapper.unmount()
  })

  it('重复选择当前商家不触发改选，避免清掉已有会话', async () => {
    const { wrapper, auth } = await mountNav()
    const select = vi.spyOn(auth, 'selectByDisplayName')

    await wrapper.get('[data-testid="merchant-switcher"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家100"]').trigger('click')

    expect(select).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('英文模式下条目文案切到英文', async () => {
    i18n.global.locale.value = 'en-US'
    const { wrapper } = await mountNav()

    expect(wrapper.get('[data-nav-item="home"]').text()).toBe('Home')
    expect(wrapper.get('[data-nav-item="knowledge-base"]').text()).toBe('Knowledge base')
    wrapper.unmount()
  })

  it('偏好设置面板在 DOM 里紧跟触发按钮，打开后焦点移进面板', async () => {
    const { wrapper } = await mountNav()
    const trigger = wrapper.get<HTMLButtonElement>('[data-testid="preferences-trigger"]')

    trigger.element.focus()
    await trigger.trigger('click')
    await flushPromises()

    const dialog = wrapper.get('[role="dialog"]')
    // Tab 顺序：触发按钮之后紧接着就是面板，不会跳过刚打开的对话框。
    expect(trigger.element.nextElementSibling).toBe(dialog.element)
    expect(dialog.element.contains(document.activeElement)).toBe(true)
    wrapper.unmount()
  })

  it('面板里按 Escape 关闭，焦点回到触发按钮', async () => {
    const { wrapper } = await mountNav()
    const trigger = wrapper.get<HTMLButtonElement>('[data-testid="preferences-trigger"]')
    await trigger.trigger('click')
    await flushPromises()

    const focused = document.activeElement as HTMLElement
    focused.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    )
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })
})
