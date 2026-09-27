/**
 * 提交订单的幂等与不可用项处理（C4）。
 *
 * - `client_request_id` 在同一次提交意图内复用：网络失败重试用同一个，服务端据此重放首次结果，
 *   不会重复占库。购物车或优惠券变化即视为新意图，换新 id。
 * - 成功或被服务端明确拒绝后，下次提交是新意图，换新 id。
 * - 不可用项（库存不足、下架）逐项返回给界面，**不**改动购物车。
 * - 金额一律来自后端响应，这里不做任何运算。
 */
import { ApiError, NetworkError } from '@/api/errors'
import { submitOrder } from '@/api/shopApi'
import type { Order, StockBand } from '@/types/shop'

export interface UnavailableItem {
  productId: string
  reason: 'OUT_OF_STOCK' | 'INSUFFICIENT_STOCK' | 'DELISTED'
  stockBand: StockBand
}

export type CheckoutResult =
  | { kind: 'placed'; order: Order }
  | { kind: 'unavailable'; items: UnavailableItem[] }

export interface CheckoutIntent {
  couponId: string | null
  /** 购物车内容的稳定指纹，只用来判断「是不是同一次提交意图」。 */
  cartSignature: string
}

export interface CheckoutOptions {
  maxNetworkRetries?: number
  retryDelayMs?: number
}

function newRequestId(): string {
  return crypto.randomUUID()
}

function toUnavailable(error: ApiError): UnavailableItem[] {
  return error.details.map((detail) => ({
    productId: String(detail.product_id),
    reason: detail.reason as UnavailableItem['reason'],
    stockBand: detail.stock_band as StockBand,
  }))
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export function createCheckout({ maxNetworkRetries = 2, retryDelayMs = 400 }: CheckoutOptions = {}) {
  let pending: { id: string; signature: string } | null = null

  async function submit(intent: CheckoutIntent): Promise<CheckoutResult> {
    const signature = `${intent.cartSignature}|${intent.couponId ?? ''}`
    if (!pending || pending.signature !== signature) pending = { id: newRequestId(), signature }
    const { id } = pending

    for (let attempt = 0; ; attempt += 1) {
      try {
        const order = await submitOrder({ clientRequestId: id, couponId: intent.couponId })
        pending = null
        return { kind: 'placed', order }
      } catch (error) {
        if (error instanceof NetworkError) {
          // 请求可能已到达服务端：不换 id，重试或由顾客再点一次都会重放同一结果。
          if (attempt < maxNetworkRetries) {
            await delay(retryDelayMs)
            continue
          }
          throw error
        }
        // 服务端给出了明确结论：这次意图结束。
        pending = null
        if (
          error instanceof ApiError &&
          (error.code === 'INSUFFICIENT_STOCK' || error.code === 'PRODUCT_NOT_IN_SCOPE') &&
          error.details.length > 0
        ) {
          return { kind: 'unavailable', items: toUnavailable(error) }
        }
        throw error
      }
    }
  }

  return { submit }
}
