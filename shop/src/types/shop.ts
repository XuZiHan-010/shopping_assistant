export type StockBand = 'IN_STOCK' | 'LOW_STOCK' | 'OUT_OF_STOCK'
export type TranslationStatus = 'SOURCE' | 'MACHINE' | 'FALLBACK'
export type ProductLocale = 'zh-CN' | 'en-US'

export interface StoreProfile {
  shopSlug: string
  displayName: string
  rulesSummary: string
}

export interface Product {
  id: string
  name: string
  shortDescription: string
  priceCents: number
  stockBand: StockBand
  imageUrl: string | null
  sourceLocale: 'zh-CN' | 'en-US' | 'mixed' | 'und'
  contentVersion: number
  requestedLocale: ProductLocale
  nameTranslationStatus: TranslationStatus
  shortDescriptionTranslationStatus: TranslationStatus
}

export interface ProductAttribute {
  name: string
  /** 商家未填写时为 null；界面显示「商家未提供」，不留空、不隐藏该行。 */
  value: string | null
  source: 'MERCHANT' | 'DEMO'
  nameTranslationStatus: TranslationStatus
  valueTranslationStatus: TranslationStatus
}

export interface ProductDetail extends Product {
  description: string
  attributes: ProductAttribute[]
  descriptionTranslationStatus: TranslationStatus
}

export interface Coupon {
  id: string
  name: string
  kind: 'AMOUNT_OFF' | 'PERCENT_OFF'
  minSpendCents: number
  amountOffCents: number | null
  discountBps: number | null
  productIds: string[]
  startsAt: string
  endsAt: string
}

export interface CartItem {
  productId: string
  name: string
  imageUrl: string | null
  quantity: number
  unitPriceCents: number
  lineTotalCents: number
  stockBand: StockBand
}

export interface Cart {
  items: CartItem[]
  /** 后端给出的小计；前端不做加减乘除。 */
  subtotalCents: number
}

export type PaymentStatus = 'PENDING' | 'PAID' | 'CLOSED'
export type FulfillmentStatus =
  | 'NOT_SHIPPED'
  | 'SHIPPED'
  | 'IN_TRANSIT'
  | 'OUT_FOR_DELIVERY'
  | 'DELIVERED'
export type AfterSaleStatus = 'NONE' | 'ACTIVE' | 'CLOSED'
export type CloseReason = 'USER_CANCELLED' | 'PAYMENT_TIMEOUT'

export interface OrderLine {
  orderItemId: string
  productId: string
  name: string
  quantity: number
  unitPriceCents: number
  discountCents: number
  lineTotalCents: number
}

export interface Order {
  id: string
  paymentStatus: PaymentStatus
  fulfillmentStatus: FulfillmentStatus
  afterSaleStatus: AfterSaleStatus
  totalCents: number
  itemCount: number
  createdAt: string
  payBy: string
  items: OrderLine[]
  subtotalCents: number
  discountCents: number
  couponId: string | null
  paidAt: string | null
  closedAt: string | null
  closeReason: CloseReason | null
}

export interface FulfillmentEvent {
  id: string
  eventType: string
  occurredAt: string
  sourceTimezone: string
}
