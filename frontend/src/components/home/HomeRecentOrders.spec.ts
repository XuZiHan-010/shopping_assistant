/**
 * 首页「最近订单」（W Task 8，契约 §8.12.4）：取订单列表前 3 条；只列平台交易链路订单，
 * 顾客只以店铺级别名出现（R5）；与首页订单量的口径差异如实说明。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'

import { i18n } from '@/i18n'
import { setLocaleProvider } from '@/api/credentials'
import { useLocaleStore } from '@/stores/locale'
import {
  failing,
  idleNever,
  idleNow,
  json,
  pinnedSessionPinia,
  routeFetch,
  TEST_BASE_URL,
  type RouteHandler,
} from '@/testing/homeHarness'
import { jsonResponse, orderSummary, page } from '@/testing/homePayloads'
import { deferred } from '@/testing/workspacePayloads'
import { routes } from '@/router'

import HomeRecentOrders from './HomeRecentOrders.vue'

async function mountOrders(handler: RouteHandler, idle: typeof idleNow = idleNow) {
  const pinia = pinnedSessionPinia()
  const fetchMock = vi.fn(routeFetch([['/api/v2/merchant/orders', handler]]))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('requestIdleCallback', idle)
  const router = createRouter({ history: createWebHistory(), routes })
  const wrapper = mount(HomeRecentOrders, { global: { plugins: [pinia, i18n, router] } })
  await flushPromises()
  return { wrapper, fetchMock }
}

beforeEach(() => {
  setLocaleProvider(() => useLocaleStore().locale)
  vi.stubEnv('VITE_API_BASE_URL', TEST_BASE_URL)
})

afterEach(() => {
  setLocaleProvider(undefined)
  i18n.global.locale.value = 'zh-CN'
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('HomeRecentOrders', () => {
  it('切语言后刷新别名并忽略晚到的旧语言响应', async () => {
    const old = deferred<Response>()
    const { wrapper } = await mountOrders((_url, init) =>
      new Headers(init?.headers).get('Accept-Language') === 'en-US'
        ? Promise.resolve(jsonResponse(page([orderSummary('o-1', { buyer_alias: 'Buyer R5T1' })])))
        : old.promise,
    )
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    expect(wrapper.text()).toContain('Buyer R5T1')
    old.resolve(jsonResponse(page([orderSummary('o-1')])))
    await flushPromises()
    expect(wrapper.text()).not.toContain('顾客 R5T1')
    wrapper.unmount()
  })
  it('空闲前不请求订单', async () => {
    const { fetchMock } = await mountOrders(json(page([])), idleNever)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('只请求 3 条，且最多展示 3 条', async () => {
    const orders = ['o-1', 'o-2', 'o-3', 'o-4'].map((id) => orderSummary(id))
    const { wrapper, fetchMock } = await mountOrders(json(page(orders, true)))

    const url = new URL(String(fetchMock.mock.calls[0]![0]))
    expect(url.searchParams.get('limit')).toBe('3')
    expect(wrapper.findAll('[data-test=recent-order]')).toHaveLength(3)
    expect(wrapper.text()).not.toContain('o-4')
  })

  it('每行显示首件商品、顾客别名、金额与状态', async () => {
    const { wrapper } = await mountOrders(
      json(
        page([
          orderSummary('o-1'),
          orderSummary('o-2', { payment_status: 'PENDING' }),
          orderSummary('o-3', { fulfillment_status: 'DELIVERED', after_sale_status: 'ACTIVE' }),
        ]),
      ),
    )
    const rows = wrapper.findAll('[data-test=recent-order]')
    expect(rows[0]!.text()).toContain('棉麻休闲衬衫')
    expect(rows[0]!.text()).toContain('顾客 R5T1')
    expect(rows[0]!.text()).toContain('530.00')
    expect(rows[0]!.text()).toContain('待发货')
    expect(rows[1]!.text()).toContain('待支付')
    expect(rows[2]!.text()).toContain('售后中')
  })

  it('「全部订单」链接到订单页；说明只列平台交易订单、与首页订单量口径不同', async () => {
    const { wrapper } = await mountOrders(json(page([orderSummary('o-1')])))
    expect(wrapper.get('[data-test=recent-orders-all]').attributes('href')).toBe('/orders')
    const note = wrapper.get('[data-test=recent-orders-scope]').text()
    expect(note).toContain('平台交易')
    expect(note).toContain('历史导入')
  })

  it('没有订单时显示空态', async () => {
    const { wrapper } = await mountOrders(json(page([])))
    expect(wrapper.find('[data-test=recent-orders-empty]').exists()).toBe(true)
  })

  it('取数失败后可重试，重试成功即显示订单', async () => {
    let fail = true
    const { wrapper, fetchMock } = await mountOrders((url, init) =>
      fail ? failing()(url, init) : json(page([orderSummary('o-1')]))(url, init),
    )
    expect(wrapper.get('[role=alert]').text()).toContain('最近订单暂时无法读取')

    fail = false
    await wrapper.get('[data-test=recent-orders-retry]').trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('[data-test=recent-order]')).toHaveLength(1)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
  })

  it('取数失败时只显示本区块不可用', async () => {
    const { wrapper } = await mountOrders(failing())
    expect(wrapper.get('[role=alert]').text()).toContain('最近订单暂时无法读取')
    expect(wrapper.findAll('[data-test=recent-order]')).toHaveLength(0)
  })
})
