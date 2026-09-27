'use client'

import { formatEventTime, formatPrice } from '@/lib/format'
import {
  AFTER_SALE_LABEL,
  CLOSE_REASON_LABEL,
  EVENT_LABEL,
  FULFILLMENT_LABEL,
  PAYMENT_LABEL,
} from '@/lib/labels'
import type { FulfillmentEvent, Order } from '@/types/shop'

export interface OrderViewProps {
  order: Order
  events: FulfillmentEvent[]
  paying: boolean
  error: string | null
  onPay: () => void
}

/**
 * 订单与履约（C5）。支付、履约、售后三个状态分开展示（D14⑥）；
 * 「已关闭」以后端状态为准，前端不自行计时判定；本版没有物流公司与运单号，因此不渲染相关字段。
 */
export function OrderView({ order, events, paying, error, onPay }: OrderViewProps) {
  return (
    <div className="stack">
      <h1>订单详情</h1>

      <dl className="card card-body" aria-label="订单状态">
        <div>
          <dt className="muted">支付状态</dt>
          <dd style={{ margin: 0 }}>{PAYMENT_LABEL[order.paymentStatus]}</dd>
        </div>
        <div>
          <dt className="muted">履约状态</dt>
          <dd style={{ margin: 0 }}>{FULFILLMENT_LABEL[order.fulfillmentStatus]}</dd>
        </div>
        <div>
          <dt className="muted">售后状态</dt>
          <dd style={{ margin: 0 }}>{AFTER_SALE_LABEL[order.afterSaleStatus]}</dd>
        </div>
      </dl>

      {order.paymentStatus === 'CLOSED' && order.closeReason ? (
        <p className="notice">{CLOSE_REASON_LABEL[order.closeReason]}</p>
      ) : null}

      {order.paymentStatus === 'PENDING' ? (
        <section className="card card-body" aria-label="支付">
          <p className="notice notice-demo" style={{ margin: 0 }}>
            演示支付，不产生真实扣款。
          </p>
          <p className="muted" style={{ margin: 0 }}>
            订单将在 30 分钟内未支付时由系统关闭并释放库存，是否关闭以订单状态为准。
          </p>
          <button className="btn btn-primary" disabled={paying} onClick={onPay}>
            模拟支付
          </button>
        </section>
      ) : null}

      {error ? (
        <div className="notice notice-error" role="alert">
          {error}
        </div>
      ) : null}

      <section className="card card-body" aria-label="商品明细">
        <h2>商品明细</h2>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {order.items.map((line) => (
            <li key={line.orderItemId} className="row spread">
              <span>
                {line.name} × {line.quantity}
              </span>
              <span>{formatPrice(line.lineTotalCents)}</span>
            </li>
          ))}
        </ul>
        {order.discountCents > 0 ? (
          <div className="row spread">
            <span className="muted">优惠</span>
            <span>-{formatPrice(order.discountCents)}</span>
          </div>
        ) : null}
        <div className="row spread">
          <span>合计</span>
          <span className="price">{formatPrice(order.totalCents)}</span>
        </div>
      </section>

      <section className="card card-body" aria-label="订单事件">
        <h2>订单事件</h2>
        <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {events.map((event) => (
            <li key={event.id} className="row spread">
              <span>{EVENT_LABEL[event.eventType] ?? event.eventType}</span>
              <span className="muted">
                {formatEventTime(event.occurredAt)}（来源时区 {event.sourceTimezone}）
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
