'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, NetworkError } from '@/api/errors'
import { listCoupons } from '@/api/catalogApi'
import { removeCartItem, setCartItem } from '@/api/shopApi'
import { createCheckout, type UnavailableItem } from '@/checkout/checkout'
import { useLocale } from '@/i18n/LocaleProvider'
import type { MessageKey } from '@/i18n/messages'
import { CartView } from '@/components/CartView'
import { useShop } from '@/session/ShopContext'
import type { Coupon } from '@/types/shop'

function describeError(error: unknown, t: (key: MessageKey) => string): string {
  if (error instanceof NetworkError) return t('cart.networkRetry')
  if (error instanceof ApiError) {
    if (error.code === 'CUSTOMER_BINDING_REQUIRED') return t('cart.bindRequired')
    if (error.code === 'INSUFFICIENT_STOCK') return t('cart.insufficient')
    if (error.code === 'RATE_LIMITED') return t('cart.rateLimited')
    return error.message
  }
  return t('operationFailed')
}

/** 购物车与结账页：购物车状态以服务端为准，金额只展示后端给的值。 */
export function CartPanel() {
  const { locale, t } = useLocale()
  const { shopSlug, session, cart, setCart, refreshCart, bindDemoCustomer, closePanel } = useShop()
  const router = useRouter()
  const checkout = useRef(createCheckout())
  const [coupons, setCoupons] = useState<Coupon[]>([])
  const [couponId, setCouponId] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState<UnavailableItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let active = true
    listCoupons(shopSlug, locale).then(
      (items) => { if (active) setCoupons(items) },
      () => { if (active) setCoupons([]) },
    )
    return () => { active = false }
  }, [shopSlug, locale])

  useEffect(() => {
    if (session) void refreshCart().catch(() => undefined)
  }, [session?.sessionId, refreshCart]) // eslint-disable-line react-hooks/exhaustive-deps

  const cartSignature = useMemo(
    () => (cart?.items ?? []).map((item) => `${item.productId}:${item.quantity}`).join(','),
    [cart],
  )

  async function guarded(action: () => Promise<void>) {
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(describeError(caught, t))
    }
  }

  return (
    <CartView
      session={session}
      cart={cart}
      coupons={coupons}
      couponId={couponId}
      unavailable={unavailable}
      error={error}
      submitting={submitting}
      onCouponChange={setCouponId}
      onQuantityChange={(productId, quantity) =>
        void guarded(async () => {
          setUnavailable([])
          setCart(await setCartItem(productId, quantity))
        })
      }
      onRemove={(productId) =>
        void guarded(async () => {
          setUnavailable([])
          setCart(await removeCartItem(productId))
        })
      }
      onBind={() => void guarded(async () => void (await bindDemoCustomer()))}
      onSubmit={() =>
        void guarded(async () => {
          setSubmitting(true)
          setUnavailable([])
          try {
            const result = await checkout.current.submit({ couponId, cartSignature })
            if (result.kind === 'unavailable') {
              setUnavailable(result.items)
              return
            }
            await refreshCart().catch(() => undefined)
            closePanel()
            router.push(`/${shopSlug}/orders/${result.order.id}`)
          } finally {
            setSubmitting(false)
          }
        })
      }
    />
  )
}
