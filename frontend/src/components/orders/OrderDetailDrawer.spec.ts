/**
 * 订单详情抽屉（W Task 9，契约 §8.12.4 `GET /api/v2/merchant/orders/{order_id}`）：
 * 价格快照、三个状态维度、顾客只以别名出现（R5）、没有任何写操作按钮；
 * 可访问对话框（打开移焦、Esc 关闭）；慢响应不能覆盖后打开的订单。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { setLocaleProvider } from '@/api/credentials'
import { useLocaleStore } from '@/stores/locale'
import {
  failing,
  json,
  pinnedSessionPinia,
  routeFetch,
  TEST_BASE_URL,
  type RouteHandler,
} from '@/testing/homeHarness'
import { jsonResponse } from '@/testing/homePayloads'
import { deferred, orderDetail } from '@/testing/workspacePayloads'

import OrderDetailDrawer from './OrderDetailDrawer.vue'

async function mountDrawer(handler: RouteHandler, orderId = 'order-1') {
  const pinia = pinnedSessionPinia()
  const fetchMock = vi.fn(routeFetch([['/api/v2/merchant/orders/', handler]]))
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(OrderDetailDrawer, {
    props: { orderId },
    attachTo: document.body,
    global: { plugins: [pinia, i18n] },
  })
  await flushPromises()
  return { wrapper, fetchMock }
}

beforeEach(() => {
  setLocaleProvider(() => useLocaleStore().locale)
  vi.stubEnv('VITE_API_BASE_URL', TEST_BASE_URL)
})

afterEach(() => {
  setLocaleProvider(undefined)
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  i18n.global.locale.value = 'zh-CN'
  document.body.innerHTML = ''
})

describe('OrderDetailDrawer', () => {
  it('详情打开时切语言刷新后端别名', async () => {
    const { wrapper } = await mountDrawer((_url, init) =>
      jsonResponse(
        orderDetail('order-1', {
          buyer_alias:
            new Headers(init?.headers).get('Accept-Language') === 'en-US'
              ? 'Buyer R5T1'
              : '顾客 R5T1',
        }),
      ),
    )
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    expect(wrapper.text()).toContain('Buyer R5T1')
    expect(wrapper.text()).not.toContain('顾客 R5T1')
    wrapper.unmount()
  })
  it('按订单号请求详情，是带标题的模态对话框', async () => {
    const { wrapper, fetchMock } = await mountDrawer(json(orderDetail('order-1')))

    const url = new URL(String(fetchMock.mock.calls[0]![0]))
    expect(url.pathname).toBe('/api/v2/merchant/orders/order-1')
    const dialog = wrapper.get('[role=dialog]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    const labelledBy = dialog.attributes('aria-labelledby')!
    expect(wrapper.get(`#${labelledBy}`).text()).toContain('订单详情')
  })

  it('显示价格快照：逐行单价、数量、优惠、小计，以及合计、优惠与实付', async () => {
    const { wrapper } = await mountDrawer(json(orderDetail('order-1')))

    const lines = wrapper.findAll('[data-test=snapshot-line]')
    expect(lines).toHaveLength(2)
    expect(lines[0]!.text()).toContain('棉麻休闲衬衫')
    expect(lines[0]!.text()).toContain('2')
    expect(lines[0]!.text()).toContain('199.00')
    expect(lines[0]!.text()).toContain('18.00')
    expect(lines[0]!.text()).toContain('380.00')
    expect(lines[1]!.text()).toContain('帆布托特包')
    expect(wrapper.get('[data-test=snapshot-subtotal]').text()).toContain('518.00')
    expect(wrapper.get('[data-test=snapshot-discount]').text()).toContain('18.00')
    expect(wrapper.get('[data-test=snapshot-total]').text()).toContain('500.00')
  })

  it('没有优惠时显示 ¥0.00，不出现负零', async () => {
    const { wrapper } = await mountDrawer(json(orderDetail('order-1', { discount_cents: 0 })))
    const text = wrapper.get('[data-test=snapshot-discount]').text()
    expect(text).toContain('0.00')
    expect(text).not.toContain('-')
  })

  it('三个状态维度都显示，各自带标签', async () => {
    const { wrapper } = await mountDrawer(
      json(
        orderDetail('order-1', {
          payment_status: 'PAID',
          fulfillment_status: 'IN_TRANSIT',
          after_sale_status: 'ACTIVE',
        }),
      ),
    )
    expect(wrapper.get('[data-test=status-payment]').text()).toContain('支付')
    expect(wrapper.get('[data-test=status-payment]').text()).toContain('已支付')
    expect(wrapper.get('[data-test=status-fulfillment]').text()).toContain('运输中')
    expect(wrapper.get('[data-test=status-after-sale]').text()).toContain('售后中')
  })

  it('已关闭订单显示关闭原因；待支付订单显示支付截止', async () => {
    const closed = await mountDrawer(
      json(
        orderDetail('order-1', {
          payment_status: 'CLOSED',
          paid_at: null,
          closed_at: '2026-09-23T06:10:00Z',
          close_reason: 'PAYMENT_TIMEOUT',
        }),
      ),
    )
    expect(closed.wrapper.text()).toContain('超时未支付')
    closed.wrapper.unmount()

    const pending = await mountDrawer(
      json(orderDetail('order-2', { payment_status: 'PENDING', paid_at: null })),
      'order-2',
    )
    expect(pending.wrapper.get('[data-test=pay-by]').text()).toContain('支付截止')
  })

  it('顾客只显示店铺别名，响应里多出的 buyer_key 不会出现在界面上（R5）', async () => {
    const payload = { ...orderDetail('order-1'), buyer_key: 'buyer-secret-key' }
    const { wrapper } = await mountDrawer(json(payload))
    expect(wrapper.get('[data-test=buyer-alias]').text()).toContain('顾客 R5T1')
    expect(wrapper.html()).not.toContain('buyer-secret-key')
  })

  it('只读：除关闭外没有任何按钮，也不发任何写请求', async () => {
    const { wrapper, fetchMock } = await mountDrawer(json(orderDetail('order-1')))
    const buttons = wrapper.findAll('button')
    expect(buttons).toHaveLength(1)
    expect(buttons[0]!.attributes('aria-label')).toBe('关闭订单详情')
    for (const call of fetchMock.mock.calls) {
      expect((call[1] as RequestInit | undefined)?.method ?? 'GET').toBe('GET')
    }
  })

  it('打开时焦点移进对话框；Esc 关闭', async () => {
    const { wrapper } = await mountDrawer(json(orderDetail('order-1')))
    const dialog = wrapper.get('[role=dialog]').element
    expect(dialog.contains(document.activeElement)).toBe(true)

    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(event)
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(event.defaultPrevented).toBe(true)
  })

  it('点遮罩或关闭按钮都发出 close', async () => {
    const { wrapper } = await mountDrawer(json(orderDetail('order-1')))
    await wrapper.get('[data-test=drawer-close]').trigger('click')
    await wrapper.get('[data-test=drawer-backdrop]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)
  })

  it('Tab 焦点困在对话框内', async () => {
    const { wrapper } = await mountDrawer(json(orderDetail('order-1')))
    const close = wrapper.get('[data-test=drawer-close]').element as HTMLElement
    close.focus()
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    close.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(wrapper.get('[role=dialog]').element.contains(document.activeElement)).toBe(true)
  })

  it('先打开 A、A 还没回来就换成 B：A 的慢响应不能覆盖 B', async () => {
    const slowA = deferred<Response>()
    const { wrapper } = await mountDrawer((url) => {
      if (url.pathname.endsWith('/order-a')) return slowA.promise
      return jsonResponse(orderDetail('order-b', { buyer_alias: '顾客 BBBB' }))
    }, 'order-a')

    await wrapper.setProps({ orderId: 'order-b' })
    await flushPromises()
    expect(wrapper.get('[data-test=buyer-alias]').text()).toContain('顾客 BBBB')

    slowA.resolve(jsonResponse(orderDetail('order-a', { buyer_alias: '顾客 AAAA' })))
    await flushPromises()
    expect(wrapper.get('[data-test=buyer-alias]').text()).toContain('顾客 BBBB')
    expect(wrapper.text()).not.toContain('顾客 AAAA')
  })

  it('读取失败显示错误与重试，重试成功后显示详情', async () => {
    let fail = true
    const { wrapper, fetchMock } = await mountDrawer((url, init) =>
      fail ? failing()(url, init) : json(orderDetail('order-1'))(url, init),
    )
    expect(wrapper.get('[role=alert]').text()).toContain('订单详情暂时无法读取')

    fail = false
    const retry = wrapper.get('[data-test=drawer-retry]')
    ;(retry.element as HTMLElement).focus()
    await retry.trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('[data-test=snapshot-line]')).toHaveLength(2)
    // 重试按钮已消失，焦点留在对话框面板上，不掉到 body（也不跑出模态框）。
    expect(document.activeElement).toBe(wrapper.get('[role=dialog]').element)
  })

  it('英文界面下标签为英文', async () => {
    const { wrapper } = await mountDrawer(json(orderDetail('order-1')))
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    expect(wrapper.text()).toContain('Order details')
    expect(wrapper.get('[data-test=status-payment]').text()).toContain('Paid')
  })
})
