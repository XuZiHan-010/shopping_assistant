/**
 * 商家订单只读面 Adapter（契约 §8.12.4，`GET /api/v2/merchant/orders`、
 * `GET /api/v2/merchant/orders/{order_id}`）。
 *
 * 顾客只以店铺级脱敏别名 `buyerAlias` 出现，响应不含 `buyerKey`（R5）；
 * 本组没有任何订单写端点。金额保持整数分，展示层换算交给 `utils/localizedFormat.ts`。
 */
import type { components } from '@/api/generated'
import type {
  MerchantOrderDetail,
  MerchantOrderSummary,
  MerchantOrdersFilter,
  OrderItemPriceSnapshot,
  OrderLeadItem,
  Page,
} from '@/types/merchantOrders'

import { merchantRequest, queryString } from './v2Http'

type RawOrderPage = components['schemas']['CursorPage_MerchantOrderSummary_']
type RawOrderSummary = components['schemas']['MerchantOrderSummary']
type RawOrderDetail = components['schemas']['MerchantOrderDetailResponse']
type RawLeadItem = components['schemas']['OrderLeadItem']
type RawItemSnapshot = components['schemas']['OrderItemPriceSnapshot']

function toLeadItem(raw: RawLeadItem): OrderLeadItem {
  return {
    productId: raw.product_id,
    name: raw.name,
    imageUrl: raw.image_url,
  }
}

function toSummary(raw: RawOrderSummary): MerchantOrderSummary {
  return {
    id: raw.id,
    paymentStatus: raw.payment_status,
    fulfillmentStatus: raw.fulfillment_status,
    afterSaleStatus: raw.after_sale_status,
    totalCents: raw.total_cents,
    itemCount: raw.item_count,
    createdAt: raw.created_at,
    payBy: raw.pay_by,
    leadItem: toLeadItem(raw.lead_item),
    lastEventAt: raw.last_event_at,
    buyerAlias: raw.buyer_alias,
    lineCount: raw.line_count,
  }
}

function toItemSnapshot(raw: RawItemSnapshot): OrderItemPriceSnapshot {
  return {
    orderItemId: raw.order_item_id,
    productId: raw.product_id,
    name: raw.name,
    quantity: raw.quantity,
    unitPriceCents: raw.unit_price_cents,
    discountCents: raw.discount_cents,
    lineTotalCents: raw.line_total_cents,
  }
}

/** 三项筛选均可选；换筛选条件或 limit 须从首页重新开始（游标绑定查询形状，§8.7.4）。 */
export async function fetchMerchantOrders(
  sessionId: string,
  options: MerchantOrdersFilter = {},
): Promise<Page<MerchantOrderSummary>> {
  const query = queryString({
    cursor: options.cursor,
    limit: options.limit,
    payment_status: options.paymentStatus,
    fulfillment_status: options.fulfillmentStatus,
    after_sale_status: options.afterSaleStatus,
  })
  const response = await merchantRequest(`/api/v2/merchant/orders${query}`, sessionId)
  const payload = (await response.json()) as RawOrderPage
  return {
    items: payload.items.map(toSummary),
    nextCursor: payload.next_cursor,
    hasMore: payload.has_more,
  }
}

/** 不存在、他店订单与历史（非 v2）订单统一 RESOURCE_FORBIDDEN；不写查看审计。 */
export async function fetchMerchantOrder(
  sessionId: string,
  orderId: string,
): Promise<MerchantOrderDetail> {
  const response = await merchantRequest(
    `/api/v2/merchant/orders/${encodeURIComponent(orderId)}`,
    sessionId,
  )
  const payload = (await response.json()) as RawOrderDetail
  return {
    id: payload.id,
    paymentStatus: payload.payment_status,
    fulfillmentStatus: payload.fulfillment_status,
    afterSaleStatus: payload.after_sale_status,
    totalCents: payload.total_cents,
    itemCount: payload.item_count,
    createdAt: payload.created_at,
    payBy: payload.pay_by,
    leadItem: toLeadItem(payload.lead_item),
    lastEventAt: payload.last_event_at,
    items: payload.items.map(toItemSnapshot),
    subtotalCents: payload.subtotal_cents,
    discountCents: payload.discount_cents,
    couponId: payload.coupon_id,
    paidAt: payload.paid_at,
    closedAt: payload.closed_at,
    closeReason: payload.close_reason,
    isDemo: payload.is_demo,
    buyerAlias: payload.buyer_alias,
  }
}
