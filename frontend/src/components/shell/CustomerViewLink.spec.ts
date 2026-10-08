import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'

import CustomerViewLink from './CustomerViewLink.vue'

const SESSION_ID = 'sid-secret'.padEnd(43, '0')
const DEMO_TOKEN = 'demo-token-secret'

function mountLink(options: { session?: boolean } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.selected = { merchantId: 'm-100', displayName: 'Borough商家100', token: DEMO_TOKEN }
  if (options.session ?? true) {
    auth.sessionId = SESSION_ID
    auth.shopSlug = 'borough-demo-100'
  }
  useLocaleStore().setLocale('zh-CN')
  return mount(CustomerViewLink, { global: { plugins: [pinia, i18n] } })
}

const link = '[data-testid="customer-view-link"]'

describe('CustomerViewLink「顾客视角」（D-N5-4）', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_SHOP_BASE_URL', 'https://shop.example.com')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it.each([undefined, '', '   '])('VITE_SHOP_BASE_URL 未配置时不渲染按钮 (%s)', (value) => {
    vi.stubEnv('VITE_SHOP_BASE_URL', value as unknown as string)

    expect(mountLink().find(link).exists()).toBe(false)
  })

  it.each(['shop.example.com', '/shop', 'javascript:alert(1)'])(
    '地址不是 http(s) 绝对地址时同样不渲染，不回退到同源 (%s)',
    (value) => {
      vi.stubEnv('VITE_SHOP_BASE_URL', value)

      expect(mountLink().find(link).exists()).toBe(false)
    },
  )

  it('链接恰为「顾客端地址 / 店铺标识」，新标签打开且不带 opener 与 referrer', () => {
    const anchor = mountLink().get(link)

    expect(anchor.attributes('href')).toBe('https://shop.example.com/borough-demo-100')
    expect(anchor.attributes('target')).toBe('_blank')
    expect(anchor.attributes('rel')?.split(' ')).toEqual(
      expect.arrayContaining(['noopener', 'noreferrer']),
    )
  })

  it('去掉顾客端地址结尾的斜杠', () => {
    vi.stubEnv('VITE_SHOP_BASE_URL', 'https://shop.example.com///')

    expect(mountLink().get(link).attributes('href')).toBe(
      'https://shop.example.com/borough-demo-100',
    )
  })

  it('链接与整个组件都不含会话 ID、演示 Token 或查询参数', () => {
    const wrapper = mountLink()
    const href = wrapper.get(link).attributes('href') ?? ''

    expect(href).not.toContain(SESSION_ID)
    expect(href).not.toContain(DEMO_TOKEN)
    expect(href).not.toMatch(/[?#]/)
    expect(wrapper.html()).not.toContain(SESSION_ID)
    expect(wrapper.html()).not.toContain(DEMO_TOKEN)
  })

  it('文案随显示语言切换', async () => {
    const wrapper = mountLink()
    expect(wrapper.get(link).text()).toContain('顾客视角')

    useLocaleStore().setLocale('en-US')
    await wrapper.vm.$nextTick()

    expect(wrapper.get(link).text()).toContain('Customer view')
    expect(wrapper.get(link).text()).not.toContain('顾客视角')
  })

  it('没有商家会话时不渲染', () => {
    expect(mountLink({ session: false }).find(link).exists()).toBe(false)
  })
})
