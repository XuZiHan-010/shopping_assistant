'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { listAfterSales } from '@/api/afterSalesApi'
import { ApiError } from '@/api/errors'
import { cancelOrder, getOrder, listOrderEvents, listOrders, payOrder } from '@/api/shopApi'
import { useChat } from '@/chat/ChatProvider'
import { useLocale } from '@/i18n/LocaleProvider'
import { formatEventTime, formatPrice } from '@/lib/format'
import { useShop } from '@/session/ShopContext'
import type { AfterSaleState, AfterSaleSummary } from '@/types/afterSales'
import type { FulfillmentEvent, Order, OrderSummaryView } from '@/types/shop'
import { ProductArt } from './ProductArt'
import './storefront-views.css'

type Expanded = { kind: 'loading' } | { kind: 'missing' } | { kind: 'error' } | { kind: 'ready'; order: Order; events: FulfillmentEvent[] }
async function fetchDetail(id: string): Promise<Expanded> {
  try {
    const [order, events] = await Promise.all([getOrder(id), listOrderEvents(id)])
    return { kind: 'ready', order, events }
  } catch (caught) {
    return { kind: caught instanceof ApiError && [401, 403, 404].includes(caught.status) ? 'missing' : 'error' }
  }
}
const EVENT_KEYS = {
  ORDER_PLACED: 'ev.ORDER_PLACED', PAYMENT_CONFIRMED: 'ev.PAYMENT_CONFIRMED', SHIPPED: 'ev.SHIPPED',
  IN_TRANSIT: 'ev.IN_TRANSIT', OUT_FOR_DELIVERY: 'ev.OUT_FOR_DELIVERY', DELIVERED: 'ev.DELIVERED', ORDER_CLOSED: 'ev.ORDER_CLOSED',
} as const
const caseKey = (state: AfterSaleState) => `case.${state}` as const

function statusKey(order: OrderSummaryView) {
  if (order.paymentStatus === 'CLOSED') return 'st.CLOSED' as const
  if (order.paymentStatus === 'PENDING') return 'st.PENDING' as const
  return `st.${order.fulfillmentStatus}` as const
}

export function OrdersView({ shopSlug, initialOrderId }: { shopSlug: string; initialOrderId?: string }) {
  const { session } = useShop()
  return <PrincipalOrders key={`${session?.sessionId ?? 'guest'}:${session?.isBound ?? false}`} shopSlug={shopSlug} initialOrderId={initialOrderId} />
}

function PrincipalOrders({ shopSlug, initialOrderId }: { shopSlug: string; initialOrderId?: string }) {
  const { session, bindDemoCustomer } = useShop()
  const { locale, t } = useLocale()
  const { send } = useChat()
  const router = useRouter()
  const bound = session?.isBound === true
  const [orders, setOrders] = useState<OrderSummaryView[]>([])
  const [cases, setCases] = useState<AfterSaleSummary[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(initialOrderId ?? null)
  const [expanded, setExpanded] = useState<Expanded | null>(initialOrderId ? { kind: 'loading' } : null)
  const [listError, setListError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  /** 幂等键按「操作 + 订单」区分：同一单的重试复用，换一单绝不复用（否则后端判为同键不同输入）。 */
  const requestIds = useRef(new Map<string, string>())

  const refresh = useCallback(async () => {
    const [orderRows, caseRows] = await Promise.all([listOrders(), listAfterSales()])
    setOrders(orderRows); setCases(caseRows)
  }, [])
  const loadDetail = useCallback(async (id: string) => {
    setExpanded(await fetchDetail(id))
  }, [])
  useEffect(() => {
    if (!bound) return
    let active = true
    Promise.all([listOrders(), listAfterSales()]).then(([orderRows, caseRows]) => {
      if (active) { setOrders(orderRows); setCases(caseRows) }
    }).catch(() => { if (active) setListError(t('orders.loadFailed')) })
    return () => { active = false }
  }, [bound, locale]) // eslint-disable-line react-hooks/exhaustive-deps -- t 随渲染重建，语言值才是请求边界
  useEffect(() => {
    if (!bound || !expandedId) return
    let active = true
    void fetchDetail(expandedId).then(value => { if (active) setExpanded(value) })
    return () => { active = false }
  }, [bound, expandedId])

  function toggle(id: string) {
    setActionError(null)
    setExpandedId(current => current === id ? null : id)
    setExpanded(expandedId === id ? null : { kind: 'loading' })
  }
  async function act(kind: 'pay' | 'cancel', id: string) {
    if (busy) return
    setBusy(true); setActionError(null)
    const key = `${kind}:${id}`
    const requestId = requestIds.current.get(key) ?? crypto.randomUUID()
    requestIds.current.set(key, requestId)
    // 只刷新正在展开的那一单；对未展开的行做快捷操作时，不能把别的订单详情换掉。
    const reloadIfExpanded = async () => { if (expandedId === id) await loadDetail(id) }
    try {
      if (kind === 'pay') await payOrder(id, requestId)
      else await cancelOrder(id, requestId)
      requestIds.current.delete(key)
      await refresh()
      await reloadIfExpanded()
    } catch (caught) {
      if (caught instanceof ApiError) {
        requestIds.current.delete(key)
        setActionError(caught.code === 'ILLEGAL_STATE_TRANSITION' ? t('orders.illegalState') : caught.message)
        await reloadIfExpanded()
      } else setActionError(t('orders.networkRetry'))
    } finally { setBusy(false) }
  }
  async function ask(id: string) {
    router.push(`/${encodeURIComponent(shopSlug)}`)
    await send(t('askOrder', { id }))
  }
  const visibleOrders = expanded?.kind === 'ready' && !orders.some(item => item.id === expanded.order.id) ? [expanded.order, ...orders] : orders
  function row(order: OrderSummaryView) {
    const selected = expandedId === order.id
    const href = `/${encodeURIComponent(shopSlug)}/after-sales?order=${encodeURIComponent(order.id)}`
    return <div className="ws-order" key={order.id}>
      <button className="ws-order-row" aria-expanded={selected} onClick={() => toggle(order.id)}>
        <ProductArt src={order.leadItem.imageUrl} alt="" size={54} />
        <span className="ws-order-main"><strong>{order.leadItem.name}{order.itemCount > 1 ? t('more', { n: order.itemCount - 1 }) : ''}</strong><small>{order.id}</small></span>
        <span className="ws-order-meta"><span className="ws-status">{t(statusKey(order))}</span><small>{order.paymentStatus === 'PENDING' ? t('payBy', { t: formatEventTime(order.payBy, locale) }) : t('updated', { t: formatEventTime(order.lastEventAt, locale) })}</small></span>
        <strong className="ws-order-price">{formatPrice(order.totalCents)}</strong>
      </button>
      <div className="ws-order-quick">
        {order.paymentStatus === 'PENDING' && <><button className="ws-solid" disabled={busy} onClick={() => void act('pay', order.id)}>{t('payNow')}</button><button className="ws-ghost" disabled={busy} onClick={() => void act('cancel', order.id)}>{t('cancel')}</button></>}
        {order.paymentStatus === 'PAID' && order.fulfillmentStatus === 'DELIVERED' && order.afterSaleStatus === 'NONE' && <Link className="ws-ghost" href={href}>{t('afterSale')}</Link>}
        <button className="ws-ghost" onClick={() => void ask(order.id)}>{t('askClerk')}</button>
      </div>
      {selected && <div className="ws-order-detail" aria-label={t('orders.detailLabel')}>
        {expanded?.kind === 'loading' && <p>{t('loading')}</p>}
        {expanded?.kind === 'missing' && <p>{t('orders.missing')}</p>}
        {expanded?.kind === 'error' && <p role="alert">{t('orders.loadFailed')}</p>}
        {expanded?.kind === 'ready' && expanded.order.id === order.id && <div className="ws-order-columns">
          <section><h3>{t('items_h')}</h3><ul className="ws-order-lines">{expanded.order.items.map(item => <li key={item.orderItemId}><span>{item.name} × {item.quantity}</span><strong>{formatPrice(item.lineTotalCents)}</strong></li>)}</ul><p className="ws-order-total"><span>{t('total')}</span><strong>{formatPrice(expanded.order.totalCents)}</strong></p>{expanded.order.paymentStatus === 'PENDING' && <p className="ws-demo-pay">{t('orders.demoPay')}</p>}{expanded.order.paymentStatus === 'CLOSED' && expanded.order.closeReason && <p>{expanded.order.closeReason === 'PAYMENT_TIMEOUT' ? t('orders.closedTimeout') : t('orders.closedCancelled')}</p>}</section>
          <section><h3>{t('track_h')}</h3><ol className="ws-timeline">{expanded.events.map(event => <li key={event.id}><span>{event.eventType in EVENT_KEYS ? t(EVENT_KEYS[event.eventType as keyof typeof EVENT_KEYS]) : event.eventType}</span><small>{formatEventTime(event.occurredAt, locale)} · {event.sourceTimezone}</small></li>)}</ol></section>
        </div>}
      </div>}
    </div>
  }

  return <div className="ws-orders">
    <header className="ws-view-head"><h1>{t('ordersTitle')}</h1><p>{bound ? t('ordersSub') : t('ordersSubGuest')}</p></header>
    {!bound ? <div className="ws-empty"><p>{t('ordersBindPrompt')}</p><button className="ws-solid" onClick={() => void bindDemoCustomer()}>{t('bind')}</button></div> : <>
      {listError && <p role="alert" className="ws-error">{listError}</p>}
      {actionError && <p role="alert" className="ws-error">{actionError}</p>}
      {initialOrderId && !orders.some(item => item.id === initialOrderId) && expanded?.kind === 'missing' && <p role="alert">{t('orders.missing')}</p>}
      <section className="ws-order-group"><h2>{t('grpActive')}</h2>{visibleOrders.filter(item => item.paymentStatus === 'PENDING' || (item.paymentStatus === 'PAID' && item.fulfillmentStatus !== 'DELIVERED')).map(row)}{visibleOrders.length === 0 && <p>{t('noOrders')}</p>}</section>
      <section className="ws-order-group"><h2>{t('grpDone')}</h2>{visibleOrders.filter(item => item.paymentStatus === 'CLOSED' || (item.paymentStatus === 'PAID' && item.fulfillmentStatus === 'DELIVERED')).map(row)}</section>
      <section className="ws-order-group"><h2>{t('grpAS')}</h2>{cases.length ? cases.map(item => <Link key={item.id} className="ws-case-row" href={`/${encodeURIComponent(shopSlug)}/after-sales?case=${encodeURIComponent(item.id)}`}><span>{item.id}</span><span>{item.orderId}</span><span>{t(caseKey(item.state))}</span></Link>) : <p>{t('orders.noCases')}</p>}</section>
    </>}
  </div>
}
