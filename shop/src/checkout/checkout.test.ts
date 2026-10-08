import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetSessionForTest, setSession } from '@/api/credentials'
import { apiErrorBody, json, stubBackend } from '@/test/fakeBackend'
import { createCheckout } from './checkout'

const order = {
  id: 'o1', payment_status: 'PENDING', fulfillment_status: 'NOT_SHIPPED', after_sale_status: 'NONE',
  total_cents: 25900, item_count: 1, created_at: '2026-09-01T00:00:00Z', pay_by: '2026-09-01T00:30:00Z',
  lead_item: { product_id: 'p1', name: '演示商品', image_url: null }, last_event_at: '2026-09-01T00:00:00Z',
  items: [], subtotal_cents: 25900, discount_cents: 0, coupon_id: null, paid_at: null, closed_at: null,
  close_reason: null, is_demo: true,
}

beforeEach(() => {
  resetSessionForTest()
  setSession({ sessionId: 'sess-1', shopSlug: 'borough-100', isBound: true, expiresAt: '2099-01-01T00:00:00Z' })
})
afterEach(() => vi.unstubAllGlobals())

const ids = (calls: { body: unknown }[]) => calls.map((c) => (c.body as { client_request_id: string }).client_request_id)

describe('C4 提交订单', () => {
  it('网络重试复用同一 client_request_id', async () => {
    let attempt = 0
    const backend = stubBackend({
      'POST /api/v2/shop/orders': () => {
        if (++attempt === 1) throw new TypeError('fetch failed')
        return json(201, order)
      },
    })
    const checkout = createCheckout({ retryDelayMs: 0 })
    const result = await checkout.submit({ couponId: null, cartSignature: 'cart-a' })

    expect(result.kind).toBe('placed')
    const sent = ids(backend.called('POST /api/v2/shop/orders'))
    expect(sent).toHaveLength(2)
    expect(new Set(sent).size).toBe(1)
  })

  it('成功后下一次提交换新的 client_request_id', async () => {
    const backend = stubBackend({ 'POST /api/v2/shop/orders': () => json(201, order) })
    const checkout = createCheckout({ retryDelayMs: 0 })
    await checkout.submit({ couponId: null, cartSignature: 'cart-a' })
    await checkout.submit({ couponId: null, cartSignature: 'cart-a' })
    expect(new Set(ids(backend.calls)).size).toBe(2)
  })

  it('购物车或优惠券变化后不再沿用旧的 client_request_id', async () => {
    const backend = stubBackend({
      'POST /api/v2/shop/orders': () => {
        throw new TypeError('offline')
      },
    })
    const checkout = createCheckout({ retryDelayMs: 0, maxNetworkRetries: 0 })
    await checkout.submit({ couponId: null, cartSignature: 'cart-a' }).catch(() => undefined)
    await checkout.submit({ couponId: 'c1', cartSignature: 'cart-a' }).catch(() => undefined)
    expect(new Set(ids(backend.calls)).size).toBe(2)
  })

  it('不可用项逐项返回，且不改动购物车', async () => {
    const backend = stubBackend({
      'POST /api/v2/shop/orders': () =>
        json(409, apiErrorBody('INSUFFICIENT_STOCK', '可售库存不足', [
          { product_id: 'p2', reason: 'INSUFFICIENT_STOCK', stock_band: 'LOW_STOCK' },
          { product_id: 'p3', reason: 'OUT_OF_STOCK', stock_band: 'OUT_OF_STOCK' },
        ])),
    })
    const result = await createCheckout({ retryDelayMs: 0 }).submit({ couponId: null, cartSignature: 's' })

    expect(result).toEqual({
      kind: 'unavailable',
      items: [
        { productId: 'p2', reason: 'INSUFFICIENT_STOCK', stockBand: 'LOW_STOCK' },
        { productId: 'p3', reason: 'OUT_OF_STOCK', stockBand: 'OUT_OF_STOCK' },
      ],
    })
    // 没有任何「移除购物车行」的请求：由顾客决定。
    expect(backend.calls.every((c) => !c.path.includes('/cart'))).toBe(true)
  })

  it('已下架商品同样逐项返回（403 PRODUCT_NOT_IN_SCOPE）', async () => {
    stubBackend({
      'POST /api/v2/shop/orders': () =>
        json(403, apiErrorBody('PRODUCT_NOT_IN_SCOPE', '当前操作不可使用该商品', [
          { product_id: 'p9', reason: 'DELISTED', stock_band: 'OUT_OF_STOCK' },
        ])),
    })
    const result = await createCheckout({ retryDelayMs: 0 }).submit({ couponId: null, cartSignature: 's' })
    expect(result).toMatchObject({ kind: 'unavailable', items: [{ productId: 'p9', reason: 'DELISTED' }] })
  })

  it('其他错误原样抛出，不吞掉', async () => {
    stubBackend({ 'POST /api/v2/shop/orders': () => json(403, apiErrorBody('CUSTOMER_BINDING_REQUIRED')) })
    await expect(createCheckout({ retryDelayMs: 0 }).submit({ couponId: null, cartSignature: 's' })).rejects.toMatchObject({
      code: 'CUSTOMER_BINDING_REQUIRED',
    })
  })
})
