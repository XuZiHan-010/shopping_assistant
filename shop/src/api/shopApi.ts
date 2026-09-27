/**
 * 顾客端**需要会话**的 API 门面：client + adapter。公开的店铺/商品读取在 catalogApi.ts，
 * 它不碰会话凭证，因此可以放心在服务端组件里使用。
 * 需要会话的调用从内存凭证里取 `X-Session-Id`；没有会话时抛 `NoSessionError`。
 */
import type { Cart, FulfillmentEvent, Order } from '@/types/shop'
import { toCart, toFulfillmentEvent, toOrder } from './adapters/shop'
import { requestJson } from './client'
import { getSession } from './credentials'
import type { components } from './generated'

type S = components['schemas']

export class NoSessionError extends Error {
  constructor() {
    super('NoSessionError')
    this.name = 'NoSessionError'
  }
}

function sessionId(): string {
  const session = getSession()
  if (!session) throw new NoSessionError()
  return session.sessionId
}

export async function getCart(): Promise<Cart> {
  return toCart(await requestJson<S['CartResponse']>('/api/v2/shop/cart', { sessionId: sessionId() }))
}

export async function setCartItem(productId: string, quantity: number): Promise<Cart> {
  return toCart(
    await requestJson<S['CartResponse']>(`/api/v2/shop/cart/items/${encodeURIComponent(productId)}`, {
      method: 'PUT',
      body: { quantity },
      sessionId: sessionId(),
    }),
  )
}

export async function removeCartItem(productId: string): Promise<Cart> {
  return toCart(
    await requestJson<S['CartResponse']>(`/api/v2/shop/cart/items/${encodeURIComponent(productId)}`, {
      method: 'DELETE',
      sessionId: sessionId(),
    }),
  )
}

export interface SubmitOrderInput {
  clientRequestId: string
  couponId?: string | null
}

export async function submitOrder(input: SubmitOrderInput): Promise<Order> {
  return toOrder(
    await requestJson<S['OrderDetailResponse']>('/api/v2/shop/orders', {
      method: 'POST',
      body: { client_request_id: input.clientRequestId, coupon_id: input.couponId ?? null },
      sessionId: sessionId(),
    }),
  )
}

export async function getOrder(orderId: string): Promise<Order> {
  return toOrder(
    await requestJson<S['OrderDetailResponse']>(`/api/v2/shop/orders/${encodeURIComponent(orderId)}`, {
      sessionId: sessionId(),
    }),
  )
}

export async function listOrderEvents(orderId: string): Promise<FulfillmentEvent[]> {
  const page = await requestJson<S['FulfillmentEventPage']>(
    `/api/v2/shop/orders/${encodeURIComponent(orderId)}/events?limit=100`,
    { sessionId: sessionId() },
  )
  return page.items.map(toFulfillmentEvent)
}

export async function payOrder(orderId: string, clientRequestId: string): Promise<Order> {
  return toOrder(
    await requestJson<S['OrderDetailResponse']>(`/api/v2/shop/orders/${encodeURIComponent(orderId)}/pay`, {
      method: 'POST',
      body: { client_request_id: clientRequestId },
      sessionId: sessionId(),
    }),
  )
}

export async function cancelOrder(orderId: string, clientRequestId: string): Promise<Order> {
  return toOrder(
    await requestJson<S['OrderDetailResponse']>(`/api/v2/shop/orders/${encodeURIComponent(orderId)}/cancel`, {
      method: 'POST',
      body: { client_request_id: clientRequestId },
      sessionId: sessionId(),
    }),
  )
}
