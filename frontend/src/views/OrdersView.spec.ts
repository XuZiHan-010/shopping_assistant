/**
 * 订单页（W Task 9，契约 §8.12.4）：三项筛选、游标翻页（换筛选必须丢掉旧游标）、
 * 详情抽屉；顾客只以别名出现（R5）；没有任何写操作按钮；顶部说明只列平台交易链路订单
 * （W Task 0 步骤 3 的口径，与首页「最近订单」同一句）。
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
import { errorResponse, jsonResponse, orderSummary, page } from '@/testing/homePayloads'
import { deferred, orderDetail } from '@/testing/workspacePayloads'

import OrdersView from './OrdersView.vue'

const LIST = '/api/v2/merchant/orders'

function listCalls(fetchMock: ReturnType<typeof vi.fn>): URL[] {
  return fetchMock.mock.calls
    .map((call) => new URL(String(call[0])))
    .filter((url) => url.pathname === LIST)
}

async function mountOrders(list: RouteHandler, detail?: RouteHandler) {
  const pinia = pinnedSessionPinia()
  const fetchMock = vi.fn(
    routeFetch([
      [`${LIST}/`, detail ?? json(orderDetail('order-1'))],
      [LIST, list],
    ]),
  )
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(OrdersView, {
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

describe('OrdersView', () => {
  it('切语言从第一页刷新，晚到的旧语言翻页不能混入新列表', async () => {
    const oldPage = deferred<Response>()
    const { wrapper, fetchMock } = await mountOrders((url, init) => {
      if (url.searchParams.has('cursor')) return oldPage.promise
      const english = new Headers(init?.headers).get('Accept-Language') === 'en-US'
      return jsonResponse(
        page(
          [orderSummary('order-1', { buyer_alias: english ? 'Buyer R5T1' : '顾客 R5T1' })],
          !english,
        ),
      )
    })
    await wrapper.get('[data-test=orders-load-more]').trigger('click')
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    expect(listCalls(fetchMock).at(-1)!.searchParams.get('cursor')).toBeNull()
    expect(wrapper.text()).toContain('Buyer R5T1')
    oldPage.resolve(jsonResponse(page([orderSummary('old-order', { buyer_alias: '旧语言顾客' })])))
    await flushPromises()
    expect(wrapper.findAll('[data-test=order-row]')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('旧语言顾客')
    wrapper.unmount()
  })
  it('顶部说明只列平台交易链路订单，与首页最近订单口径同一句', async () => {
    const { wrapper } = await mountOrders(json(page([])))
    expect(wrapper.get('h1').text()).toBe('订单')
    const scope = wrapper.get('[data-test=orders-scope]').text()
    expect(scope).toBe(i18n.global.t('home.orders.scope'))
    expect(scope).toContain('平台交易')
    expect(scope).toContain('历史导入')
  })

  it('进入页面即请求第一页，不带游标与筛选；每行显示别名、首件商品、金额与状态', async () => {
    const { wrapper, fetchMock } = await mountOrders(
      json(
        page([
          orderSummary('order-1'),
          orderSummary('order-2', { payment_status: 'PENDING', buyer_alias: '顾客 P2Q9' }),
          orderSummary('order-3', {
            fulfillment_status: 'DELIVERED',
            after_sale_status: 'ACTIVE',
          }),
        ]),
      ),
    )
    const [first] = listCalls(fetchMock)
    expect(first!.searchParams.get('cursor')).toBeNull()
    expect(first!.searchParams.get('payment_status')).toBeNull()
    expect(first!.searchParams.get('fulfillment_status')).toBeNull()
    expect(first!.searchParams.get('after_sale_status')).toBeNull()

    const rows = wrapper.findAll('[data-test=order-row]')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.text()).toContain('顾客 R5T1')
    expect(rows[0]!.text()).toContain('棉麻休闲衬衫')
    expect(rows[0]!.text()).toContain('530.00')
    expect(rows[0]!.text()).toContain('已支付')
    expect(rows[0]!.text()).toContain('待发货')
    expect(rows[1]!.text()).toContain('顾客 P2Q9')
    expect(rows[1]!.text()).toContain('待支付')
    expect(rows[2]!.text()).toContain('已签收')
    expect(rows[2]!.text()).toContain('售后中')
  })

  it('响应里多出的 buyer_key 不会出现在界面上（R5）', async () => {
    const leaked = { ...orderSummary('order-1'), buyer_key: 'buyer-secret-key' }
    const { wrapper } = await mountOrders(json(page([leaked])))
    expect(wrapper.html()).not.toContain('buyer-secret-key')
  })

  it('三项筛选分别映射到契约的查询参数', async () => {
    const { wrapper, fetchMock } = await mountOrders(json(page([orderSummary('order-1')])))

    await wrapper.get('[data-test=filter-payment]').setValue('PAID')
    await flushPromises()
    await wrapper.get('[data-test=filter-fulfillment]').setValue('IN_TRANSIT')
    await flushPromises()
    await wrapper.get('[data-test=filter-after-sale]').setValue('ACTIVE')
    await flushPromises()

    const last = listCalls(fetchMock).at(-1)!
    expect(last.searchParams.get('payment_status')).toBe('PAID')
    expect(last.searchParams.get('fulfillment_status')).toBe('IN_TRANSIT')
    expect(last.searchParams.get('after_sale_status')).toBe('ACTIVE')
    expect(last.searchParams.get('cursor')).toBeNull()
  })

  it('加载更多带上游标与当前筛选并追加；换筛选后从第一页重来，不带旧游标', async () => {
    const { wrapper, fetchMock } = await mountOrders((url) => {
      const cursor = url.searchParams.get('cursor')
      if (cursor === 'cursor-next') return jsonResponse(page([orderSummary('order-2')]))
      return jsonResponse(page([orderSummary('order-1')], true))
    })

    await wrapper.get('[data-test=filter-payment]').setValue('PAID')
    await flushPromises()
    await wrapper.get('[data-test=orders-load-more]').trigger('click')
    await flushPromises()

    const more = listCalls(fetchMock).at(-1)!
    expect(more.searchParams.get('cursor')).toBe('cursor-next')
    expect(more.searchParams.get('payment_status')).toBe('PAID')
    expect(wrapper.findAll('[data-test=order-row]')).toHaveLength(2)
    expect(wrapper.find('[data-test=orders-load-more]').exists()).toBe(false)

    await wrapper.get('[data-test=filter-fulfillment]').setValue('NOT_SHIPPED')
    await flushPromises()
    const reset = listCalls(fetchMock).at(-1)!
    expect(reset.searchParams.get('cursor')).toBeNull()
    expect(reset.searchParams.get('payment_status')).toBe('PAID')
    expect(reset.searchParams.get('fulfillment_status')).toBe('NOT_SHIPPED')
    expect(wrapper.findAll('[data-test=order-row]')).toHaveLength(1)
  })

  it('翻页中途换筛选：旧筛选的「加载更多」响应晚到也不会追加到新列表', async () => {
    const slowMore = deferred<Response>()
    const { wrapper } = await mountOrders((url) => {
      if (url.searchParams.get('cursor') === 'cursor-next') return slowMore.promise
      if (url.searchParams.get('payment_status') === 'PENDING') {
        return jsonResponse(page([orderSummary('order-pending', { buyer_alias: '顾客 NEW1' })]))
      }
      return jsonResponse(page([orderSummary('order-1')], true))
    })

    await wrapper.get('[data-test=orders-load-more]').trigger('click')
    await wrapper.get('[data-test=filter-payment]').setValue('PENDING')
    await flushPromises()

    slowMore.resolve(
      jsonResponse(page([orderSummary('order-stale', { buyer_alias: '顾客 OLD9' })])),
    )
    await flushPromises()

    const rows = wrapper.findAll('[data-test=order-row]')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.text()).toContain('顾客 NEW1')
    expect(wrapper.text()).not.toContain('顾客 OLD9')
  })

  it('先发的慢请求晚到，不覆盖后发请求的结果', async () => {
    const slowFirst = deferred<Response>()
    let calls = 0
    const { wrapper } = await mountOrders(() => {
      calls += 1
      if (calls === 1) return slowFirst.promise
      return jsonResponse(page([orderSummary('order-new', { buyer_alias: '顾客 NEW1' })]))
    })

    await wrapper.get('[data-test=filter-after-sale]').setValue('ACTIVE')
    await flushPromises()
    slowFirst.resolve(jsonResponse(page([orderSummary('order-old', { buyer_alias: '顾客 OLD9' })])))
    await flushPromises()

    expect(wrapper.text()).toContain('顾客 NEW1')
    expect(wrapper.text()).not.toContain('顾客 OLD9')
  })

  it('「加载更多」遇到 INVALID_CURSOR 时从第一页重新读取，礼貌提示且焦点不掉到 body', async () => {
    const { wrapper, fetchMock } = await mountOrders((url) => {
      if (url.searchParams.get('cursor')) return errorResponse(422, 'INVALID_CURSOR')
      return jsonResponse(page([orderSummary('order-1')], true))
    })
    expect(wrapper.find('[data-test=orders-restarted]').exists()).toBe(false)
    const loadMore = wrapper.get('[data-test=orders-load-more]')
    ;(loadMore.element as HTMLElement).focus()
    await loadMore.trigger('click')
    await flushPromises()

    const last = listCalls(fetchMock).at(-1)!
    expect(last.searchParams.get('cursor')).toBeNull()
    expect(wrapper.findAll('[data-test=order-row]')).toHaveLength(1)
    const notice = wrapper.get('[data-test=orders-restarted]')
    expect(notice.element.closest('[role=status]')).not.toBeNull()
    expect(notice.text()).toContain('已从第一页重新加载')
    expect(document.activeElement).toBe(wrapper.get('[data-test=orders-panel]').element)

    // 用户主动换筛选后，提示随之消失。
    await wrapper.get('[data-test=filter-payment]').setValue('PAID')
    await flushPromises()
    expect(wrapper.find('[data-test=orders-restarted]').exists()).toBe(false)
  })

  it('「加载更多」其他失败时保留已加载的订单，并可重试', async () => {
    let fail = true
    const { wrapper } = await mountOrders((url) => {
      if (url.searchParams.get('cursor')) {
        return fail ? errorResponse(503) : jsonResponse(page([orderSummary('order-2')]))
      }
      return jsonResponse(page([orderSummary('order-1')], true))
    })
    await wrapper.get('[data-test=orders-load-more]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test=order-row]')).toHaveLength(1)
    expect(wrapper.get('[data-test=orders-more-error]').text()).toContain('更多订单暂时无法读取')

    fail = false
    await wrapper.get('[data-test=orders-load-more]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test=order-row]')).toHaveLength(2)
  })

  it('没有订单时显示空态；有筛选时空态说明是筛选无结果', async () => {
    const { wrapper } = await mountOrders(json(page([])))
    expect(wrapper.get('[data-test=orders-empty]').text()).toContain('还没有平台交易订单')

    await wrapper.get('[data-test=filter-payment]').setValue('CLOSED')
    await flushPromises()
    expect(wrapper.get('[data-test=orders-empty]').text()).toContain('没有符合当前筛选的订单')

    await wrapper.get('[data-test=filters-clear]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test=filter-payment]').element).toHaveProperty('value', '')
  })

  it('读取失败显示错误与重试，重试成功后显示订单', async () => {
    let fail = true
    const { wrapper } = await mountOrders((url, init) =>
      fail ? failing()(url, init) : json(page([orderSummary('order-1')]))(url, init),
    )
    expect(wrapper.get('[role=alert]').text()).toContain('订单暂时无法读取')

    fail = false
    await wrapper.get('[data-test=orders-retry]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test=order-row]')).toHaveLength(1)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    // 重试按钮随错误态消失，焦点落到列表面板而不是 body。
    expect(document.activeElement).toBe(wrapper.get('[data-test=orders-panel]').element)
  })

  it('点订单打开详情抽屉；Esc 关闭后焦点回到该订单', async () => {
    const { wrapper, fetchMock } = await mountOrders(
      json(page([orderSummary('order-1'), orderSummary('order-2')])),
      json(orderDetail('order-2')),
    )
    const trigger = wrapper.findAll('[data-test=order-open]')[1]!
    await trigger.trigger('click')
    await flushPromises()

    const detailCall = fetchMock.mock.calls
      .map((call) => new URL(String(call[0])))
      .find((url) => url.pathname.startsWith(`${LIST}/`))
    expect(detailCall!.pathname).toBe(`${LIST}/order-2`)
    expect(wrapper.find('[role=dialog]').exists()).toBe(true)

    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    )
    await flushPromises()
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  it('没有任何写操作按钮，也不发任何写请求', async () => {
    const { wrapper, fetchMock } = await mountOrders(
      json(page([orderSummary('order-1')], true)),
      json(orderDetail('order-1')),
    )
    await wrapper.get('[data-test=order-open]').trigger('click')
    await flushPromises()

    const allowed = new Set(['order-open', 'orders-load-more', 'filters-clear', 'drawer-close'])
    for (const button of wrapper.findAll('button')) {
      expect(allowed.has(button.attributes('data-test') ?? '')).toBe(true)
    }
    for (const call of fetchMock.mock.calls) {
      expect((call[1] as RequestInit | undefined)?.method ?? 'GET').toBe('GET')
    }
  })

  it('英文界面下筛选与说明为英文', async () => {
    const { wrapper } = await mountOrders(json(page([orderSummary('order-1')])))
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    expect(wrapper.get('[data-test=orders-scope]').text()).toContain('Platform checkout orders')
    expect(wrapper.text()).toContain('Payment')
    expect(wrapper.text()).toContain('To ship')
  })
})
