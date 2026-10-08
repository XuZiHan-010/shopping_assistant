import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'
import { setLocaleProvider } from '@/api/credentials'

import { fetchMerchantOrder, fetchMerchantOrders } from './merchantOrders'

const BASE_URL = 'http://127.0.0.1:8000'
const SESSION = 's'.repeat(43)

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function errorResponse(code: string, status: number): Response {
  return jsonResponse(
    { code, message: 'boom', request_id: 'req-1', details: [], retryable: false },
    status,
  )
}

function orderSummary(overrides: Record<string, unknown> = {}) {
  return {
    id: 'o-1',
    payment_status: 'PAID',
    fulfillment_status: 'SHIPPED',
    after_sale_status: 'NONE',
    total_cents: 25900,
    item_count: 1,
    created_at: '2026-09-20T00:00:00Z',
    pay_by: '2026-09-20T00:30:00Z',
    lead_item: { product_id: 'p-1', name: '羊绒围巾', image_url: null },
    last_event_at: '2026-09-20T01:00:00Z',
    buyer_alias: '顾客****88',
    line_count: 1,
    ...overrides,
  }
}

describe('merchantOrders adapter', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    setLocaleProvider(undefined)
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('拉取订单列表并转成领域类型，带上会话头', async () => {
    setLocaleProvider(() => 'en-US')
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ items: [orderSummary()], next_cursor: 'cur-1', has_more: true }),
      )
    vi.stubGlobal('fetch', fetchMock)

    const page = await fetchMerchantOrders(SESSION, { limit: 20 })

    expect(page.items[0]).toEqual({
      id: 'o-1',
      paymentStatus: 'PAID',
      fulfillmentStatus: 'SHIPPED',
      afterSaleStatus: 'NONE',
      totalCents: 25900,
      itemCount: 1,
      createdAt: '2026-09-20T00:00:00Z',
      payBy: '2026-09-20T00:30:00Z',
      leadItem: { productId: 'p-1', name: '羊绒围巾', imageUrl: null },
      lastEventAt: '2026-09-20T01:00:00Z',
      buyerAlias: '顾客****88',
      lineCount: 1,
    })
    expect(page.nextCursor).toBe('cur-1')
    expect(page.hasMore).toBe(true)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/orders?limit=20`)
    expect((init.headers as Record<string, string>)['X-Session-Id']).toBe(SESSION)
    expect(new Headers(init.headers).get('Accept-Language')).toBe('en-US')
  })

  it('三项筛选与游标一起拼进查询参数', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ items: [], next_cursor: null, has_more: false }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchMerchantOrders(SESSION, {
      cursor: 'cur-0',
      paymentStatus: 'PAID',
      fulfillmentStatus: 'SHIPPED',
      afterSaleStatus: 'ACTIVE',
    })

    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('cursor=cur-0')
    expect(url).toContain('payment_status=PAID')
    expect(url).toContain('fulfillment_status=SHIPPED')
    expect(url).toContain('after_sale_status=ACTIVE')
  })

  it('未指定筛选时查询参数里不出现筛选键', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ items: [], next_cursor: null, has_more: false }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchMerchantOrders(SESSION)

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/api/v2/merchant/orders`)
  })

  it('伪造游标转成 INVALID_CURSOR 的 AppError，不可重试', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse('INVALID_CURSOR', 422)))

    const error = await fetchMerchantOrders(SESSION, { cursor: 'stale' }).catch((cause) => cause)

    expect(error).toBeInstanceOf(AppError)
    expect((error as AppError).code).toBe('INVALID_CURSOR')
  })

  it('拉取订单详情并转成领域类型，含订单行价格快照', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        ...orderSummary({ after_sale_status: 'CLOSED' }),
        items: [
          {
            order_item_id: 'oi-1',
            product_id: 'p-1',
            name: '羊绒围巾',
            quantity: 1,
            unit_price_cents: 25900,
            discount_cents: 0,
            line_total_cents: 25900,
          },
        ],
        subtotal_cents: 25900,
        discount_cents: 0,
        coupon_id: null,
        paid_at: '2026-09-20T00:10:00Z',
        closed_at: null,
        close_reason: null,
        is_demo: true,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const detail = await fetchMerchantOrder(SESSION, 'o-1')

    expect(detail.items[0]).toEqual({
      orderItemId: 'oi-1',
      productId: 'p-1',
      name: '羊绒围巾',
      quantity: 1,
      unitPriceCents: 25900,
      discountCents: 0,
      lineTotalCents: 25900,
    })
    expect(detail.buyerAlias).toBe('顾客****88')
    expect(detail.isDemo).toBe(true)
    expect(detail.closedAt).toBeNull()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/orders/o-1`)
    expect((init.headers as Record<string, string>)['X-Session-Id']).toBe(SESSION)
  })

  it('跨店铺或不存在的订单转成 RESOURCE_FORBIDDEN 的 AppError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse('RESOURCE_FORBIDDEN', 403)))

    const error = await fetchMerchantOrder(SESSION, 'other-shop-order').catch((cause) => cause)

    expect(error).toBeInstanceOf(AppError)
    expect((error as AppError).code).toBe('RESOURCE_FORBIDDEN')
  })

  it('订单 id 会做 URL 编码', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        orderSummary({
          items: [],
          subtotal_cents: 0,
          discount_cents: 0,
          coupon_id: null,
          paid_at: null,
          closed_at: null,
          close_reason: null,
          is_demo: true,
        }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchMerchantOrder(SESSION, 'o/1?x').catch(() => undefined)

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/api/v2/merchant/orders/o%2F1%3Fx`)
  })

  it('Adapter 不对金额做浮点换算（金额只在渲染层用 localizedFormat 转换）', async () => {
    const { readFileSync } = await import('node:fs')
    const src = readFileSync('src/api/adapters/merchantOrders.ts', 'utf-8')
    expect(src).not.toMatch(/_cents\s*\/\s*100/)
  })
})
