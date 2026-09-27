'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { ApiError } from '@/api/errors'
import { getOrder, listOrderEvents, payOrder } from '@/api/shopApi'
import { OrderView } from '@/components/OrderView'
import { useShop } from '@/session/ShopContext'
import type { FulfillmentEvent, Order } from '@/types/shop'

type State =
  | { kind: 'loading' }
  | { kind: 'missing' }
  | { kind: 'error' }
  | { kind: 'ready'; order: Order; events: FulfillmentEvent[] }

async function fetchOrder(orderId: string): Promise<State> {
  try {
    const [order, events] = await Promise.all([getOrder(orderId), listOrderEvents(orderId)])
    return { kind: 'ready', order, events }
  } catch (caught) {
    // 目标不存在与不属于当前主体使用同一个公开错误：这里也渲染成同一个页面。
    const denied = caught instanceof ApiError && [401, 403, 404].includes(caught.status)
    return { kind: denied ? 'missing' : 'error' }
  }
}

export function OrderClient({ orderId, shopSlug }: { orderId: string; shopSlug: string }) {
  const { session } = useShop()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [paying, setPaying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 同一次支付意图复用 client_request_id：重试重放首次结果，不会重复扣占用。
  const payRequestId = useRef<string | null>(null)
  const signedIn = session !== null
  const isBound = session?.isBound === true

  // 绑定演示身份后会话 ID 不变但可见范围变了，所以 isBound 也是重新加载的依据。
  useEffect(() => {
    if (!signedIn) return
    let cancelled = false
    void fetchOrder(orderId).then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [signedIn, isBound, orderId])

  const load = useCallback(async () => setState(await fetchOrder(orderId)), [orderId])

  async function pay() {
    setPaying(true)
    setError(null)
    payRequestId.current ??= crypto.randomUUID()
    try {
      await payOrder(orderId, payRequestId.current)
      payRequestId.current = null
      await load()
    } catch (caught) {
      if (caught instanceof ApiError) {
        payRequestId.current = null
        setError(caught.code === 'ILLEGAL_STATE_TRANSITION' ? '订单当前状态不允许支付，请刷新查看。' : caught.message)
        await load()
      } else {
        setError('网络异常，请重试；重试不会重复扣款。')
      }
    } finally {
      setPaying(false)
    }
  }

  if (state.kind === 'loading') return <p className="muted">加载中…</p>
  if (state.kind === 'missing') {
    return (
      <div className="stack">
        <h1>订单不存在</h1>
        <p className="muted">
          没有找到这个订单。如果刚刚刷新过页面，请先绑定演示顾客后再查看。
        </p>
      </div>
    )
  }
  if (state.kind === 'error') {
    return (
      <p className="notice notice-error" role="alert">
        暂时无法加载订单，请稍后重试。
      </p>
    )
  }
  return (
    <div className="stack">
      <OrderView order={state.order} events={state.events} paying={paying} error={error} onPay={() => void pay()} />
      {state.order.paymentStatus === 'PAID' && (
        <Link className="btn" href={`/${encodeURIComponent(shopSlug)}/after-sales?order=${encodeURIComponent(orderId)}`}>
          申请售后
        </Link>
      )}
    </div>
  )
}
