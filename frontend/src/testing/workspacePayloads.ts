/**
 * 订单页与商品页（W Task 9）组件测试共用的后端原始载荷。
 *
 * 与 `homePayloads.ts` 同样的约定：只供 `*.spec.ts` 引用，按 `generated.ts` 的原始 schema
 * 书写（snake_case），让测试经过真实 Adapter 的字段映射。
 */
import type { components } from '@/api/generated'

type S = components['schemas']

export function orderDetail(
  id: string,
  overrides: Partial<S['MerchantOrderDetailResponse']> = {},
): S['MerchantOrderDetailResponse'] {
  return {
    id,
    payment_status: 'PAID',
    fulfillment_status: 'NOT_SHIPPED',
    after_sale_status: 'NONE',
    total_cents: 50000,
    item_count: 3,
    created_at: '2026-09-23T05:40:00Z',
    pay_by: '2026-09-23T06:10:00Z',
    lead_item: { product_id: `p-${id}`, name: '棉麻休闲衬衫', image_url: null },
    last_event_at: '2026-09-23T05:41:00Z',
    items: [
      {
        order_item_id: `${id}-line-1`,
        product_id: `p-${id}`,
        name: '棉麻休闲衬衫',
        quantity: 2,
        unit_price_cents: 19900,
        discount_cents: 1800,
        line_total_cents: 38000,
      },
      {
        order_item_id: `${id}-line-2`,
        product_id: `p-${id}-2`,
        name: '帆布托特包',
        quantity: 1,
        unit_price_cents: 12000,
        discount_cents: 0,
        line_total_cents: 12000,
      },
    ],
    subtotal_cents: 51800,
    discount_cents: 1800,
    coupon_id: null,
    paid_at: '2026-09-23T05:45:00Z',
    closed_at: null,
    close_reason: null,
    is_demo: true,
    buyer_alias: '顾客 R5T1',
    ...overrides,
  }
}

export function productContent(
  id: string,
  overrides: Partial<S['MerchantProductContent']> = {},
): S['MerchantProductContent'] {
  return {
    id,
    title: `测试商品 ${id}`,
    category: '男装',
    status: 'ONLINE',
    content_version: 3,
    missing_required_attributes: [],
    missing_content_fields: [],
    content_complete: true,
    stock_on_hand: 12,
    stock_reserved: 2,
    stock_available: 10,
    ...overrides,
  }
}

/** 可由测试手动放行的响应：用来制造「先发后到」的慢请求。 */
export function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
