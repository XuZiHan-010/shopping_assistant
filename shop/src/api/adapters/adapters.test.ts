import { describe, expect, it } from 'vitest'
import type { components } from '../generated'
import { toCart, toOrder, toProductDetail } from './shop'

type S = components['schemas']

describe('wire → 领域模型', () => {
  it('商品详情：属性保留来源，空值归一为 null', () => {
    const raw: S['ProductDetailResponse'] = {
      id: 'p1', name: '羊绒围巾', short_description: '暖', price_cents: 25900,
      stock_band: 'LOW_STOCK', image_url: null, description: '长描述', content_version: 3,
      source_locale: 'zh-CN', requested_locale: 'en-US',
      name_translation_status: 'MACHINE', short_description_translation_status: 'FALLBACK',
      description_translation_status: 'FALLBACK',
      attributes: [
        { name: '材质', value: '100% 羊绒', source: 'MERCHANT', updated_at: '2026-09-01T00:00:00Z', name_translation_status: 'MACHINE', value_translation_status: 'FALLBACK' },
        { name: '产地', value: '', source: 'MERCHANT', updated_at: '2026-09-01T00:00:00Z', name_translation_status: 'FALLBACK', value_translation_status: 'SOURCE' },
      ],
    }
    const detail = toProductDetail(raw)
    expect(detail.priceCents).toBe(25900)
    expect(detail.attributes).toEqual([
      { name: '材质', value: '100% 羊绒', source: 'MERCHANT', nameTranslationStatus: 'MACHINE', valueTranslationStatus: 'FALLBACK' },
      { name: '产地', value: null, source: 'MERCHANT', nameTranslationStatus: 'FALLBACK', valueTranslationStatus: 'SOURCE' },
    ])
    expect(detail.sourceLocale).toBe('zh-CN')
    expect(detail.requestedLocale).toBe('en-US')
    expect(detail.nameTranslationStatus).toBe('MACHINE')
    expect(detail.descriptionTranslationStatus).toBe('FALLBACK')
  })

  it('购物车：金额原样透传，不重算', () => {
    const raw: S['CartResponse'] = {
      subtotal_cents: 99999,
      items: [
        { product_id: 'p1', name: 'A', image_url: null, quantity: 2, unit_price_cents: 100, line_total_cents: 777, stock_band: 'IN_STOCK' },
      ],
    }
    const cart = toCart(raw)
    expect(cart.subtotalCents).toBe(99999)
    expect(cart.items[0]).toMatchObject({ productId: 'p1', quantity: 2, unitPriceCents: 100, lineTotalCents: 777 })
  })

  it('订单：三个状态维度各自保留', () => {
    const raw: S['OrderDetailResponse'] = {
      id: 'o1', payment_status: 'PAID', fulfillment_status: 'SHIPPED', after_sale_status: 'ACTIVE',
      total_cents: 25900, item_count: 1, created_at: '2026-09-01T00:00:00Z', pay_by: '2026-09-01T00:30:00Z',
      items: [], subtotal_cents: 25900, discount_cents: 0, coupon_id: null, paid_at: '2026-09-01T00:10:00Z',
      closed_at: null, close_reason: null, is_demo: true,
    }
    const order = toOrder(raw)
    expect([order.paymentStatus, order.fulfillmentStatus, order.afterSaleStatus]).toEqual(['PAID', 'SHIPPED', 'ACTIVE'])
    expect(order.totalCents).toBe(25900)
  })
})
