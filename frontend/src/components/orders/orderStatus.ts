/**
 * 订单三个状态维度到胶囊色调的映射（W Task 9）。
 *
 * 只按契约的三个枚举各自着色，不合成履约模型里没有的状态（如「物流停滞」，设计说明 §3.3）。
 */
import type { PillTone } from '@/components/layout/pillTone'
import type {
  FulfillmentStatus,
  MerchantOrderSummary,
  OrderAfterSaleProjection,
  PaymentStatus,
} from '@/types/merchantOrders'

export const PAYMENT_STATUSES: readonly PaymentStatus[] = ['PENDING', 'PAID', 'CLOSED']
export const FULFILLMENT_STATUSES: readonly FulfillmentStatus[] = [
  'NOT_SHIPPED',
  'SHIPPED',
  'IN_TRANSIT',
  'OUT_FOR_DELIVERY',
  'DELIVERED',
]
export const AFTER_SALE_STATUSES: readonly OrderAfterSaleProjection[] = ['NONE', 'ACTIVE', 'CLOSED']

/** 订单页三项筛选的界面状态；空串表示「全部」（不过滤）。 */
export interface OrderFilterState {
  payment: PaymentStatus | ''
  fulfillment: FulfillmentStatus | ''
  afterSale: OrderAfterSaleProjection | ''
}

export const EMPTY_ORDER_FILTERS: Readonly<OrderFilterState> = {
  payment: '',
  fulfillment: '',
  afterSale: '',
}

export function paymentTone(status: PaymentStatus): PillTone {
  if (status === 'PENDING') return 'warn'
  if (status === 'PAID') return 'ok'
  return 'muted'
}

export function fulfillmentTone(status: FulfillmentStatus): PillTone {
  return status === 'DELIVERED' ? 'ok' : 'info'
}

export function afterSaleTone(status: OrderAfterSaleProjection): PillTone {
  return status === 'ACTIVE' ? 'violet' : 'muted'
}

/**
 * 首页「最近订单」每单只显示一个胶囊（W Task 10 起与订单页共用映射与文案）。
 *
 * 优先级：售后进行中 → 待支付 / 已关闭 → 已支付时的履约状态。文案键直接复用订单页的
 * `ordersPage.afterSale.*` / `ordersPage.payment.*` / `ordersPage.fulfillment.*`，
 * 不另设一套含义相同的首页文案。
 */
export function recentOrderStatus(order: MerchantOrderSummary): {
  messageKey: string
  tone: PillTone
} {
  if (order.afterSaleStatus === 'ACTIVE') {
    return { messageKey: 'ordersPage.afterSale.ACTIVE', tone: afterSaleTone('ACTIVE') }
  }
  if (order.paymentStatus !== 'PAID') {
    return {
      messageKey: `ordersPage.payment.${order.paymentStatus}`,
      tone: paymentTone(order.paymentStatus),
    }
  }
  return {
    messageKey: `ordersPage.fulfillment.${order.fulfillmentStatus}`,
    tone: fulfillmentTone(order.fulfillmentStatus),
  }
}
