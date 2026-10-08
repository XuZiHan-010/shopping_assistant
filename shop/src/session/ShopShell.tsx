'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSession } from '@/api/credentials'
import { ApiError } from '@/api/errors'
import { getCart, listOrders } from '@/api/shopApi'
import { CartPanel } from '@/shell/CartPanel'
import { ChatProvider, useChat } from '@/chat/ChatProvider'
import { useLocale } from '@/i18n/LocaleProvider'
import { PreferencesPopover } from '@/preferences/PreferencesPopover'
import { ActivityDrawer } from '@/shell/ActivityDrawer'
import type { Cart } from '@/types/shop'
import { ProductSheet } from '@/views/ProductSheet'
import { ShopContext, type ShopContextValue } from './ShopContext'
import { bindDemoCustomer, openShopSession, switchDemoIdentity } from './sessionService'

type Phase = 'opening' | 'ready' | 'unavailable' | 'error'
type Panel = ShopContextValue['panel']

export function ShopShell({ shopSlug, children }: { shopSlug: string; children: ReactNode }) {
  const session = useSession()
  const pathname = usePathname()
  const { t } = useLocale()
  const [phase, setPhase] = useState<Phase>('opening')
  const [cart, setCart] = useState<Cart | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [panel, setPanel] = useState<Panel>(null)
  const [productId, setProductId] = useState<string | null>(null)
  const [pendingOrders, setPendingOrders] = useState<{ sessionId: string; count: number } | null>(null)
  const [identityOpen, setIdentityOpen] = useState(false)
  const view = pathname?.startsWith(`/${shopSlug}/orders`) ? 'orders' : 'assistant'
  const refreshCart = useCallback(async () => setCart(await getCart()), [])

  useEffect(() => {
    let cancelled = false
    openShopSession(shopSlug).then(async () => {
      if (cancelled) return
      setPhase('ready')
      await refreshCart().catch(() => undefined)
    }).catch((error: unknown) => {
      if (!cancelled) setPhase(error instanceof ApiError && error.status === 403 ? 'unavailable' : 'error')
    })
    return () => { cancelled = true }
  }, [shopSlug, refreshCart])

  useEffect(() => {
    if (!session?.isBound) return
    let cancelled = false
    listOrders().then(orders => {
      if (!cancelled) setPendingOrders({ sessionId: session.sessionId, count: orders.filter(order => order.paymentStatus === 'PENDING').length })
    }, () => { if (!cancelled) setPendingOrders({ sessionId: session.sessionId, count: 0 }) })
    return () => { cancelled = true }
  }, [session?.sessionId, session?.isBound, pathname])

  useEffect(() => {
    const queryPanel = new URLSearchParams(window.location.search).get('panel')
    if (queryPanel === 'cart' || queryPanel === 'memory' || queryPanel === 'history' || queryPanel === 'activity') {
      queueMicrotask(() => setPanel(queryPanel))
      const url = new URL(window.location.href)
      url.searchParams.delete('panel')
      window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
    }
  }, [pathname])

  const value = useMemo<ShopContextValue>(() => ({
    shopSlug, session, cart, refreshCart, setCart, view, panel, productId,
    openPanel: (next, id) => { setProductId(next === 'product' ? id ?? null : null); setPanel(next) },
    closePanel: () => { setPanel(null); setProductId(null) },
    bindDemoCustomer: async () => {
      const result = await bindDemoCustomer()
      if (result.cartAdjusted) setNotice(t('cartAdjusted'))
      await refreshCart()
      return result
    },
    switchIdentity: async () => {
      await switchDemoIdentity(shopSlug)
      setNotice(null); setIdentityOpen(false)
      await refreshCart().catch(() => undefined)
    },
  }), [shopSlug, session, cart, refreshCart, view, panel, productId, t])

  async function fromHeader(action: () => Promise<unknown>) {
    try { await action(); setIdentityOpen(false) }
    catch { setNotice(t('demoUnavailable')) }
  }

  const cartCount = cart?.items.reduce((count, item) => count + item.quantity, 0) ?? 0
  const visiblePending = session?.isBound && pendingOrders?.sessionId === session.sessionId ? pendingOrders.count : 0
  return <ShopContext.Provider value={value}>
    <ChatProvider>
      <a className="skip-link" href="#shop-main">{t('skip')}</a>
      <div className="shop-app" data-panel={panel ?? 'closed'}>
        <header className="shop-topbar">
          <Link href={`/${shopSlug}`} className="shop-brand" aria-label="Borough">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/borough-logo.svg" alt="" width={28} height={28} /> Borough
          </Link>
          <nav className="shop-tabs" aria-label={t('navLabel')}>
            <Link href={`/${shopSlug}`} aria-label={t('tab.assistant')} aria-current={view === 'assistant' ? 'page' : undefined}><span className="shop-tab-icon" aria-hidden="true">✦</span><span className="shop-tab-text">{t('tab.assistant')}</span></Link>
            <Link href={`/${shopSlug}/orders`} aria-label={t('tab.orders')} aria-current={view === 'orders' ? 'page' : undefined}>
              <span className="shop-tab-icon" aria-hidden="true">▤</span><span className="shop-tab-text">{t('tab.orders')}</span>{visiblePending > 0 && <span className="shop-pending" aria-label={`${visiblePending} ${t('pendingAttn')}`}>{visiblePending}</span>}
            </Link>
          </nav>
          <div className="shop-actions">
            <button type="button" className="shop-icon-button" aria-label={t('activity')} onClick={() => value.openPanel('activity')}><span aria-hidden="true">◷</span><span className="shop-action-text">{t('activity')}</span></button>
            <button type="button" className="shop-icon-button shop-cart-toggle" aria-label={t('cart')} onClick={() => value.openPanel('cart')}><span aria-hidden="true">▣</span><span className="shop-action-text">{t('cart')}</span>{cartCount > 0 && <span className="badge">{cartCount}</span>}</button>
            <div className="shop-identity">
              <button type="button" className="shop-identity-trigger" aria-expanded={identityOpen} onClick={() => setIdentityOpen(open => !open)}>
                <span data-testid="identity">{session?.isBound ? t('demo') : t('guest')}</span>
              </button>
              {identityOpen && <div className="shop-identity-menu" role="group" aria-label={session?.isBound ? t('demo') : t('guest')}>
                <p>{session?.isBound ? t('acctBound') : t('acctGuest')}</p><p className="muted">{t('notReal')}</p>
                {session?.isBound ? <button className="btn" onClick={() => void fromHeader(value.switchIdentity)}>{t('unbind')}</button>
                  : session ? <button className="btn" onClick={() => void fromHeader(value.bindDemoCustomer)}>{t('bind')}</button> : null}
              </div>}
            </div>
            <PreferencesPopover />
          </div>
        </header>
        <div className="shop-layout">
          <main id="shop-main" className="shop-main">
            {notice && <p className="notice" role="status">{notice}</p>}
            {phase === 'unavailable' ? <p className="notice notice-error" role="alert">{t('storeUnavailable')}</p>
              : phase === 'error' ? <p className="notice notice-error" role="alert">{t('serviceUnavailable')}</p> : children}
          </main>
          <aside className="shop-cart-rail" aria-label={t('cart')}>
            <div className="shop-cart-rail-head"><h2>{t('cart')}</h2><button className="shop-cart-close" aria-label={t('close')} onClick={value.closePanel}>×</button></div>
            {phase === 'ready' && <CartPanel />}
          </aside>
        </div>
        {panel === 'cart' && <button className="shop-overlay" aria-label={t('close')} onClick={value.closePanel} />}
        <ActivityDrawer open={panel === 'activity' || panel === 'memory' || panel === 'history'} onClose={value.closePanel} initialTab={panel === 'memory' ? 'memory' : panel === 'history' ? 'history' : 'steps'} onTabChange={tab => value.openPanel(tab === 'steps' ? 'activity' : tab)} />
        {panel === 'product' && productId && <ProductSheet shopSlug={shopSlug} productId={productId} onClose={value.closePanel} />}
        <ShopComposer view={view} shopSlug={shopSlug} />
        <p className="shop-demo-fine">{t('demoFine')}</p>
      </div>
    </ChatProvider>
  </ShopContext.Provider>
}

function ShopComposer({ view, shopSlug }: { view: 'assistant' | 'orders'; shopSlug: string }) {
  const { send, busy } = useChat()
  const { t } = useLocale()
  const router = useRouter()
  const [draft, setDraft] = useState('')
  return <form className="shop-composer" onSubmit={event => {
    event.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    if (view === 'orders') router.push(`/${shopSlug}`)
    void send(text)
  }}>
    <label htmlFor="shop-ask" className="sr-only">{t('askLabel')}</label>
    <textarea id="shop-ask" rows={1} aria-label={t('askLabel')} placeholder={view === 'orders' ? t('placeholderOrders') : t('placeholder')} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() }
    }} />
    <button type="submit" className="btn btn-primary" disabled={busy || !draft.trim()}>{t('send')}</button>
  </form>
}
