import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { FulfillmentEvent, Order } from '@/types/shop'
import { OrderView } from './OrderView'

const order = (over: Partial<Order> = {}): Order => ({
  id: 'o1',
  paymentStatus: 'PENDING',
  fulfillmentStatus: 'NOT_SHIPPED',
  afterSaleStatus: 'NONE',
  totalCents: 25900,
  itemCount: 1,
  createdAt: '2026-09-01T00:00:00Z',
  payBy: '2026-09-01T00:30:00Z',
  leadItem: { productId: 'p1', name: '羊绒围巾', imageUrl: null },
  lastEventAt: '2026-09-01T00:00:00Z',
  items: [
    {
      orderItemId: 'i1',
      productId: 'p1',
      name: '羊绒围巾',
      quantity: 1,
      unitPriceCents: 25900,
      discountCents: 0,
      lineTotalCents: 25900,
    },
  ],
  subtotalCents: 25900,
  discountCents: 0,
  couponId: null,
  paidAt: null,
  closedAt: null,
  closeReason: null,
  ...over,
})
const events: FulfillmentEvent[] = [
  { id: 'e1', eventType: 'ORDER_PLACED', occurredAt: '2026-09-01T00:00:00Z', sourceTimezone: 'Asia/Shanghai' },
]
const props = { events, paying: false, error: null, onPay: vi.fn() }

describe('C5 订单页', () => {
  it('支付、履约、售后三个状态各自独立展示', () => {
    render(
      <OrderView
        {...props}
        order={order({ paymentStatus: 'PAID', fulfillmentStatus: 'IN_TRANSIT', afterSaleStatus: 'ACTIVE' })}
      />,
    )
    expect(screen.getByText('支付状态').nextElementSibling).toHaveTextContent('已支付')
    expect(screen.getByText('履约状态').nextElementSibling).toHaveTextContent('运输中')
    expect(screen.getByText('售后状态').nextElementSibling).toHaveTextContent('售后处理中')
  })

  it('本版没有物流公司与运单号：不出现占位的运单号', () => {
    render(<OrderView {...props} order={order({ fulfillmentStatus: 'SHIPPED' })} />)
    expect(screen.queryByText(/运单|快递单|物流公司/)).toBeNull()
  })

  it('待支付：常驻演示支付提示并给出支付按钮', () => {
    render(<OrderView {...props} order={order()} />)
    expect(screen.getByText(/演示支付，不产生真实扣款/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '模拟支付' })).toBeEnabled()
  })

  it('已支付：不再显示支付按钮', () => {
    render(<OrderView {...props} order={order({ paymentStatus: 'PAID', paidAt: '2026-09-01T00:10:00Z' })} />)
    expect(screen.queryByRole('button', { name: '模拟支付' })).toBeNull()
  })

  it('已关闭以后端状态为准，并说明原因，不由前端计时判定', () => {
    render(
      <OrderView
        {...props}
        order={order({ paymentStatus: 'CLOSED', closeReason: 'PAYMENT_TIMEOUT', closedAt: '2026-09-01T00:30:00Z' })}
      />,
    )
    expect(screen.getByText('支付状态').nextElementSibling).toHaveTextContent('已关闭')
    expect(screen.getByText(/超时未支付/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '模拟支付' })).toBeNull()
  })

  it('待支付订单即使截止时间已过，也仍按后端状态展示为待支付', () => {
    render(<OrderView {...props} order={order({ payBy: '2000-01-01T00:00:00Z' })} />)
    expect(screen.getByText('支付状态').nextElementSibling).toHaveTextContent('待支付')
  })

  it('事件同时展示换算后的时间与来源时区', () => {
    render(<OrderView {...props} order={order()} />)
    expect(screen.getByText('已下单')).toBeInTheDocument()
    expect(screen.getByText(/Asia\/Shanghai/)).toBeInTheDocument()
  })

  it('金额直接展示后端给的合计', () => {
    render(<OrderView {...props} order={order({ totalCents: 12345 })} />)
    expect(screen.getByText('¥123.45')).toBeInTheDocument()
  })
})
