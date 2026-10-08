import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/errors'
import type { Order, OrderSummaryView } from '@/types/shop'
import { OrdersView } from './OrdersView'

const api = vi.hoisted(() => ({ listOrders: vi.fn(), getOrder: vi.fn(), listOrderEvents: vi.fn(), payOrder: vi.fn(), cancelOrder: vi.fn(), listAfterSales: vi.fn() }))
const chat = vi.hoisted(() => ({ send: vi.fn() }))
const navigate = vi.hoisted(() => ({ push: vi.fn() }))
const identity = vi.hoisted(() => ({ bound: true, bind: vi.fn() }))
vi.mock('@/api/shopApi', () => api)
vi.mock('@/api/afterSalesApi', () => ({ listAfterSales: api.listAfterSales }))
vi.mock('@/chat/ChatProvider', () => ({ useChat: () => chat }))
vi.mock('next/navigation', () => ({ useRouter: () => navigate }))
vi.mock('@/session/ShopContext', () => ({ useShop: () => ({ session: { isBound: identity.bound }, bindDemoCustomer: identity.bind }) }))

const summary = (id: string, paymentStatus: OrderSummaryView['paymentStatus'], fulfillmentStatus: OrderSummaryView['fulfillmentStatus'] = 'NOT_SHIPPED'): OrderSummaryView => ({
  id, paymentStatus, fulfillmentStatus, afterSaleStatus: 'NONE', totalCents: 25900,
  itemCount: 1, createdAt: '2026-09-01T00:00:00Z', payBy: '2026-09-01T00:30:00Z',
  leadItem: { productId: 'p1', name: '羊绒围巾', imageUrl: null }, lastEventAt: '2026-09-01T00:00:00Z',
})
const detail = (item: OrderSummaryView): Order => ({ ...item, items: [{ orderItemId: 'i1', productId: 'p1', name: '羊绒围巾', quantity: 1, unitPriceCents: 25900, discountCents: 0, lineTotalCents: 25900 }], subtotalCents: 25900, discountCents: 0, couponId: null, paidAt: null, closedAt: null, closeReason: null })

beforeEach(() => {
  vi.clearAllMocks()
  identity.bound = true
  const rows = [summary('pending', 'PENDING'), summary('delivered', 'PAID', 'DELIVERED'), summary('closed', 'CLOSED')]
  api.listOrders.mockResolvedValue(rows)
  api.getOrder.mockImplementation(async (id: string) => detail(rows.find(row => row.id === id)!))
  api.listOrderEvents.mockResolvedValue([{ id: 'e1', eventType: 'ORDER_PLACED', occurredAt: '2026-09-01T00:00:00Z', sourceTimezone: 'Asia/Shanghai' }])
  api.listAfterSales.mockResolvedValue([{ id: 'as1', orderId: 'delivered', type: 'REFUND_ONLY', state: 'PENDING_MERCHANT', refundAmountCents: null, createdAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-01T00:00:00Z' }])
  api.payOrder.mockResolvedValue(detail({ ...rows[0]!, paymentStatus: 'PAID' }))
  api.cancelOrder.mockResolvedValue(detail({ ...rows[0]!, paymentStatus: 'CLOSED' }))
})

it('按三组展示订单和售后，展开时读取详情与履约事件', async () => {
  const user = userEvent.setup()
  render(<OrdersView shopSlug="borough-100" />)
  expect(await screen.findByRole('heading', { name: '进行中' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '已完成' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '我的售后' })).toBeInTheDocument()
  expect(api.getOrder).not.toHaveBeenCalled()
  await user.click(await screen.findByRole('button', { name: /羊绒围巾.*待付款/ }))
  await waitFor(() => expect(api.getOrder).toHaveBeenCalledWith('pending'))
  expect(api.listOrderEvents).toHaveBeenCalledWith('pending')
  expect(await screen.findByText('已下单')).toBeInTheDocument()
})

it('访客只显示绑定提示，不读取任何订单或售后', async () => {
  identity.bound = false
  render(<OrdersView shopSlug="borough-100" />)
  expect(screen.getByText(/绑定演示顾客后/)).toBeInTheDocument()
  expect(api.listOrders).not.toHaveBeenCalled()
  expect(api.listAfterSales).not.toHaveBeenCalled()
})

it('订单详情路由默认展开；待付款操作复用请求 ID，已签收可申请售后', async () => {
  const user = userEvent.setup()
  render(<OrdersView shopSlug="borough-100" initialOrderId="pending" />)
  await waitFor(() => expect(api.getOrder).toHaveBeenCalledWith('pending'))
  await user.click(await screen.findByRole('button', { name: '去支付' }))
  expect(api.payOrder).toHaveBeenCalledWith('pending', expect.any(String))
  await user.click(screen.getByRole('button', { name: /羊绒围巾.*已签收/ }))
  expect(await screen.findByRole('link', { name: '申请售后' })).toHaveAttribute('href', '/borough-100/after-sales?order=delivered')
})

it('问问智能助手发送包含订单编号的问题并返回助手视图', async () => {
  const user = userEvent.setup()
  render(<OrdersView shopSlug="borough-100" />)
  await user.click((await screen.findAllByRole('button', { name: '问问智能助手' }))[0]!)
  expect(chat.send).toHaveBeenCalledWith(expect.stringContaining('pending'))
  expect(navigate.push).toHaveBeenCalledWith('/borough-100')
})

it('直达不属于当前顾客的订单使用与不存在相同的公开状态', async () => {
  api.getOrder.mockRejectedValueOnce(new ApiError(403, { code: 'HTTP_ERROR', message: 'not found' }))
  render(<OrdersView shopSlug="borough-100" initialOrderId="foreign" />)
  expect(await screen.findByText('订单不存在')).toBeInTheDocument()
  expect(screen.queryByText('not found')).toBeNull()
})

it('取消订单网络重试复用同一个幂等请求 ID', async () => {
  const user = userEvent.setup()
  api.cancelOrder.mockRejectedValueOnce(new Error('network'))
  render(<OrdersView shopSlug="borough-100" />)
  await user.click(await screen.findByRole('button', { name: '取消订单' }))
  await screen.findByRole('alert')
  await user.click(screen.getByRole('button', { name: '取消订单' }))
  await waitFor(() => expect(api.cancelOrder).toHaveBeenCalledTimes(2))
  expect(api.cancelOrder.mock.calls[0]?.[1]).toBe(api.cancelOrder.mock.calls[1]?.[1])
})

it('幂等请求 ID 按订单区分：一单网络失败后，支付另一单不复用它的 ID', async () => {
  const user = userEvent.setup()
  const rows = [summary('first', 'PENDING'), summary('second', 'PENDING')]
  api.listOrders.mockResolvedValue(rows)
  api.payOrder.mockRejectedValueOnce(new Error('network'))
  render(<OrdersView shopSlug="borough-100" />)
  const payButtons = await screen.findAllByRole('button', { name: '去支付' })
  await user.click(payButtons[0]!)
  await screen.findByRole('alert')
  await user.click(screen.getAllByRole('button', { name: '去支付' })[1]!)
  await waitFor(() => expect(api.payOrder).toHaveBeenCalledTimes(2))
  expect(api.payOrder.mock.calls.map(call => call[0])).toEqual(['first', 'second'])
  expect(api.payOrder.mock.calls[0]?.[1]).not.toBe(api.payOrder.mock.calls[1]?.[1])
})

it('对未展开的订单做快捷操作，不会替换正在展开的订单详情', async () => {
  const user = userEvent.setup()
  render(<OrdersView shopSlug="borough-100" initialOrderId="delivered" />)
  await waitFor(() => expect(api.getOrder).toHaveBeenCalledWith('delivered'))
  const detailPanel = await screen.findByLabelText('订单详情')
  expect(await within(detailPanel).findByText('已下单')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '取消订单' }))
  await waitFor(() => expect(api.cancelOrder).toHaveBeenCalledWith('pending', expect.any(String)))
  await waitFor(() => expect(api.listOrders).toHaveBeenCalledTimes(2))
  expect(api.getOrder).not.toHaveBeenCalledWith('pending')
  expect(within(screen.getByLabelText('订单详情')).getByText('已下单')).toBeInTheDocument()
})
