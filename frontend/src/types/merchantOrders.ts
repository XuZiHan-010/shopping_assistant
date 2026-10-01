/**
 * 商家订单只读面的领域类型（契约 §8.12.4）。
 *
 * 顾客只以店铺级脱敏别名 `buyerAlias` 出现，不存在 `buyerKey`（R5）。
 * 金额保持整数分，展示层换算交给 `utils/localizedFormat.ts`。
 */

export type PaymentStatus = 'PENDING' | 'PAID' | 'CLOSED'
export type FulfillmentStatus =
  | 'NOT_SHIPPED'
  | 'SHIPPED'
  | 'IN_TRANSIT'
  | 'OUT_FOR_DELIVERY'
  | 'DELIVERED'
export type OrderAfterSaleProjection = 'NONE' | 'ACTIVE' | 'CLOSED'
export type CloseReason = 'USER_CANCELLED' | 'PAYMENT_TIMEOUT'

export interface OrderLeadItem {
  productId: string
  name: string
  imageUrl: string | null
}

export interface MerchantOrderSummary {
  id: string
  paymentStatus: PaymentStatus
  fulfillmentStatus: FulfillmentStatus
  afterSaleStatus: OrderAfterSaleProjection
  totalCents: number
  itemCount: number
  createdAt: string
  payBy: string
  leadItem: OrderLeadItem
  lastEventAt: string
  /** 店铺级脱敏别名；不存在 buyerKey（R5）。 */
  buyerAlias: string
  lineCount: number
}

export interface OrderItemPriceSnapshot {
  orderItemId: string
  productId: string
  name: string
  quantity: number
  unitPriceCents: number
  discountCents: number
  lineTotalCents: number
}

export interface MerchantOrderDetail {
  id: string
  paymentStatus: PaymentStatus
  fulfillmentStatus: FulfillmentStatus
  afterSaleStatus: OrderAfterSaleProjection
  totalCents: number
  itemCount: number
  createdAt: string
  payBy: string
  leadItem: OrderLeadItem
  lastEventAt: string
  items: OrderItemPriceSnapshot[]
  subtotalCents: number
  discountCents: number
  couponId: string | null
  paidAt: string | null
  closedAt: string | null
  closeReason: CloseReason | null
  isDemo: true
  buyerAlias: string
}

export interface Page<T> {
  items: T[]
  nextCursor: string | null
  hasMore: boolean
}

export interface MerchantOrdersFilter {
  cursor?: string | null
  limit?: number
  paymentStatus?: PaymentStatus
  fulfillmentStatus?: FulfillmentStatus
  afterSaleStatus?: OrderAfterSaleProjection
}
