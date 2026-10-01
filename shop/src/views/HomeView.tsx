'use client'

import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { listProducts } from '@/api/catalogApi'
import { listOrders } from '@/api/shopApi'
import { useChat } from '@/chat/ChatProvider'
import { TranslationNote } from '@/components/TranslationNote'
import { translate } from '@/i18n/LocaleProvider'
import { pluralKey, type MessageKey } from '@/i18n/messages'
import { formatEventTime, formatPrice } from '@/lib/format'
import { useShop } from '@/session/ShopContext'
import type { Coupon, OrderSummaryView, Product, ProductLocale, StoreProfile } from '@/types/shop'
import { ProductArt } from './ProductArt'
import { ThreadView } from './ThreadView'
import styles from './HomeView.module.css'

const rank: Record<OrderSummaryView['fulfillmentStatus'] | 'PENDING', number> = {
  OUT_FOR_DELIVERY: 0, PENDING: 1, IN_TRANSIT: 2, SHIPPED: 3, NOT_SHIPPED: 4, DELIVERED: 5,
}

const quickKeys = ['home.quick1', 'home.quick2', 'home.quick3', 'home.quick4'] as const

const noSubscription = () => () => undefined
/** 以「小时 + 日期」作快照：同一小时内取值稳定，满足 useSyncExternalStore 的缓存要求。 */
function clockSnapshot(): string {
  const now = new Date()
  return `${now.getHours()}|${now.toDateString()}`
}

/**
 * 问候语与日期按**本机**时间（规格 §2），服务端时区与顾客不同（部署在 UTC、顾客在 UTC+8）。
 * 服务端与水合阶段返回 null，只在客户端挂载后渲染，避免文本水合不一致。
 */
function useClientClock(): Date | null {
  const snapshot = useSyncExternalStore(noSubscription, clockSnapshot, () => null)
  return snapshot === null ? null : new Date()
}

function isActive(order: OrderSummaryView): boolean {
  return order.paymentStatus === 'PENDING'
    || (order.paymentStatus === 'PAID' && order.fulfillmentStatus !== 'DELIVERED')
}

function orderRank(order: OrderSummaryView): number {
  return rank[order.paymentStatus === 'PENDING' ? 'PENDING' : order.fulfillmentStatus]
}

export function HomeView({ popular, store, coupons, locale, thread }: {
  popular: Product[]; store: StoreProfile; coupons: Coupon[]; locale: ProductLocale; thread?: ReactNode
}) {
  const { shopSlug, session, bindDemoCustomer, openPanel } = useShop()
  const { messages, send } = useChat()
  const router = useRouter()
  const [orderResult, setOrderResult] = useState<{ sessionId: string; orders: OrderSummaryView[] } | null>(null)
  const [allProducts, setAllProducts] = useState<{ locale: ProductLocale; products: Product[] } | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadingAll, setLoadingAll] = useState(false)
  const [orderError, setOrderError] = useState<string | null>(null)
  const bound = Boolean(session?.isBound)
  const now = useClientClock()
  const t = (key: MessageKey, vars?: Record<string, string | number>) => translate(locale, key, vars)
  const count = (key: MessageKey, n: number) => t(pluralKey(locale, key, n), { n })

  useEffect(() => {
    if (!bound) return
    let active = true
    const sessionId = session?.sessionId ?? ''
    listOrders().then(result => { if (active) { setOrderResult({ sessionId, orders: result }); setOrderError(null) } })
      .catch(() => { if (active) setOrderError(sessionId) })
    return () => { active = false }
  }, [bound, session?.sessionId])

  if (messages.length > 0) return <>{thread ?? <ThreadView onOpenHistory={() => openPanel('history')} />}</>

  const orders = bound && orderResult && orderResult.sessionId === session?.sessionId ? orderResult.orders : null
  const activeOrders = orders?.filter(isActive).sort((a, b) => orderRank(a) - orderRank(b)) ?? []
  const pendingCount = activeOrders.filter(order => order.paymentStatus === 'PENDING').length
  const deliveryCount = activeOrders.filter(order => order.paymentStatus === 'PAID' && order.fulfillmentStatus === 'OUT_FOR_DELIVERY').length
  const hour = now?.getHours()
  const greeting = hour === undefined ? null
    : t(hour < 11 ? 'morning' : hour < 18 ? 'afternoon' : 'evening') + (bound ? t('welcomeBack') : '')
  const date = now ? new Intl.DateTimeFormat(locale, { month: 'long', day: 'numeric', weekday: 'long' }).format(now) : null

  async function expandProducts() {
    if (showAll) { setShowAll(false); return }
    setShowAll(true)
    if (allProducts?.locale === locale) return
    setLoadingAll(true); setLoadError(null)
    try { setAllProducts({ locale, products: await listProducts(shopSlug, locale) }) }
    catch { setLoadError(t('home.productsFailed')) }
    finally { setLoadingAll(false) }
  }

  function askOrder(order: OrderSummaryView) {
    void send(t('askOrder', { id: order.id }))
  }

  const allInLocale = allProducts?.locale === locale ? allProducts.products : null
  const grid = showAll ? (allInLocale ?? []) : popular
  const sectionName = showAll ? t('allProducts') : t('popular')
  return (
    <div className={styles.home}>
      <header className={styles.intro}>
        {/* 挂载前用不换行空格占位，保持行高，避免水合后布局跳动。 */}
        <p className={styles.date}>{date ?? ' '}</p>
        <h1 className={styles.greeting}>{greeting ?? ' '}</h1>
        {bound && orders ? (
          <p className={styles.summary}>
            {count('home.summaryActive', activeOrders.length)}
            {deliveryCount > 0 ? count('home.summaryDelivery', deliveryCount) : ''}{t('home.summaryEnd')}
            {pendingCount > 0 ? <strong>{count('home.summaryPending', pendingCount)}</strong> : null}
          </p>
        ) : bound ? <p className={styles.summary} role="status">{orderError === session?.sessionId ? t('home.summaryUnavailable') : t('home.loadingSummary')}</p> : <p className={styles.summary}>{t('guestSummary')}</p>}
      </header>

      <div className={styles.quick} aria-label={t('home.quickLabel')}>
        {quickKeys.map((key, index) => (
          <button key={key} type="button" className={styles.quickCard} onClick={() => void send(t(key))}>
            <span className={styles.quickIcon} aria-hidden="true">{['⌕', '◇', '◌', '✎'][index]}</span>
            <span>{t(key)}</span><span className={styles.arrow} aria-hidden="true">↗</span>
          </button>
        ))}
      </div>

      <section className={styles.orderPanel} aria-label={t('onTheWay')}>
        <div className={styles.panelHead}>
          <h2>{t('onTheWay')}</h2>
          {bound && orders ? <span className={styles.muted}>{count('home.orderCount', activeOrders.length)}</span> : null}
          {bound ? <button type="button" className={styles.textAction} onClick={() => router.push(`/${shopSlug}/orders`)}>{t('allOrders')} <span aria-hidden="true">→</span></button> : null}
        </div>
        {!bound ? <div className={styles.bindPrompt}><p>{t('ordersBindPrompt')}</p><button type="button" className={styles.solidAction} onClick={() => void bindDemoCustomer()}>{t('bind')}</button></div> : (
          !orders ? <p className={styles.empty} role="status">{orderError === session?.sessionId ? t('home.ordersFailed') : t('home.ordersLoading')}</p> : activeOrders.length === 0 ? <p className={styles.empty}>{t('noOrders')}</p> :
          <ul className={styles.orderList}>
            {activeOrders.slice(0, 3).map(order => {
              const status = order.paymentStatus === 'PENDING' ? 'PENDING' : order.fulfillmentStatus
              return <li key={order.id} className={styles.orderRow}>
                <ProductArt product={order.leadItem} size="thumb" locale={locale} />
                <div className={styles.orderInfo}>
                  <strong>{order.leadItem.name}{order.itemCount > 1 ? t('more', { n: order.itemCount - 1 }) : ''}</strong>
                  <div className={styles.orderMeta}><span className={`${styles.status} ${status === 'PENDING' ? styles.warn : styles.info}`}>{t(`st.${status}`)}</span><span>{status === 'PENDING' ? t('payBy', { t: formatEventTime(order.payBy, locale) }) : t('updated', { t: formatEventTime(order.lastEventAt, locale) })}</span></div>
                </div>
                {status === 'PENDING'
                  ? <button type="button" className={styles.solidAction} onClick={() => router.push(`/${shopSlug}/orders/${order.id}`)}>{t('payNow')}</button>
                  : <button type="button" className={styles.ghostAction} onClick={() => askOrder(order)}>{t('ask')}</button>}
              </li>
            })}
          </ul>
        )}
      </section>

      <section className={styles.catalog} aria-label={sectionName}>
        <div className={styles.sectionHead}>
          <h2>{sectionName}</h2>
          <span className={styles.muted}>{showAll ? `${t('allProductsSub')}${allInLocale ? ` · ${count('home.productCount', allInLocale.length)}` : ''}` : t('popularSub')}</span>
          <button type="button" className={styles.textAction} onClick={() => void expandProducts()}>{showAll ? t('showLess') : t('allProducts')} <span aria-hidden="true">→</span></button>
        </div>
        {showAll && store.rulesSummary.trim() ? <p className={styles.rules}>{store.rulesSummary}</p> : null}
        {showAll && coupons.length > 0 ? <div className={styles.coupons}>{coupons.map(coupon => <span key={coupon.id} className={styles.coupon}>{coupon.name}</span>)}</div> : null}
        {loadError ? <p className={styles.error} role="alert">{loadError}</p> : null}
        {loadingAll ? <p className={styles.muted} role="status">{t('home.productsLoading')}</p> : null}
        <div className={styles.tiles}>
          {grid.map(product => <button type="button" key={product.id} className={styles.tile} onClick={() => openPanel('product', product.id)}>
            <ProductArt product={product} size="tile" locale={locale} />
            <span className={styles.productName}>{product.name}<TranslationNote status={product.nameTranslationStatus} locale={locale} /></span>
            <span className={styles.price}>{formatPrice(product.priceCents)}{product.stockBand !== 'IN_STOCK' ? <span className={`${styles.stock} ${product.stockBand === 'LOW_STOCK' ? styles.warn : styles.soldOut}`}>{product.stockBand === 'LOW_STOCK' ? t('stock_LOW') : t('stock_OUT')}</span> : null}</span>
          </button>)}
        </div>
      </section>
    </div>
  )
}
