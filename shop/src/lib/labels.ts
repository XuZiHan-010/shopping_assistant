import type { AfterSaleStatus, CloseReason, FulfillmentStatus, PaymentStatus } from '@/types/shop'
import type { UnavailableItem } from '@/checkout/checkout'

export const PAYMENT_LABEL: Record<PaymentStatus, string> = {
  PENDING: '待支付',
  PAID: '已支付',
  CLOSED: '已关闭',
}

export const FULFILLMENT_LABEL: Record<FulfillmentStatus, string> = {
  NOT_SHIPPED: '未发货',
  SHIPPED: '已出库',
  IN_TRANSIT: '运输中',
  OUT_FOR_DELIVERY: '派送中',
  DELIVERED: '已签收',
}

export const AFTER_SALE_LABEL: Record<AfterSaleStatus, string> = {
  NONE: '无售后',
  ACTIVE: '售后处理中',
  CLOSED: '售后已结束',
}

export const CLOSE_REASON_LABEL: Record<CloseReason, string> = {
  USER_CANCELLED: '已由你取消，库存已释放',
  PAYMENT_TIMEOUT: '超时未支付，订单已关闭，库存已释放',
}

export const EVENT_LABEL: Record<string, string> = {
  ORDER_PLACED: '已下单',
  PAYMENT_CONFIRMED: '已支付',
  SHIPPED: '已出库',
  IN_TRANSIT: '运输中',
  OUT_FOR_DELIVERY: '派送中',
  DELIVERED: '已签收',
  ORDER_CLOSED: '已关闭',
}

export const UNAVAILABLE_LABEL: Record<UnavailableItem['reason'], string> = {
  INSUFFICIENT_STOCK: '库存不足，请调整数量',
  OUT_OF_STOCK: '已售罄',
  DELISTED: '已下架',
}
