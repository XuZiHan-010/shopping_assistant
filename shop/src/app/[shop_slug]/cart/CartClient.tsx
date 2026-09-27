'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, NetworkError } from '@/api/errors'
import { listCoupons } from '@/api/catalogApi'
import { removeCartItem, setCartItem } from '@/api/shopApi'
import { createCheckout, type UnavailableItem } from '@/checkout/checkout'
import { CartView } from '@/components/CartView'
import { useShop } from '@/session/ShopContext'
import type { Coupon } from '@/types/shop'

function describeError(error: unknown): string {
  if (error instanceof NetworkError) return '网络异常，请重试；重试不会重复下单。'
  if (error instanceof ApiError) {
    if (error.code === 'CUSTOMER_BINDING_REQUIRED') return '请先绑定演示顾客再提交订单。'
    if (error.code === 'INSUFFICIENT_STOCK') return '库存不足，请调整数量。'
    if (error.code === 'RATE_LIMITED') return '请求过于频繁，请稍后再试。'
    return error.message
  }
  return '操作失败，请稍后重试。'
}

/** 购物车与结账页：购物车状态以服务端为准，金额只展示后端给的值。 */
export function CartClient() {
  const { shopSlug, session, cart, setCart, refreshCart, bindDemoCustomer } = useShop()
  const router = useRouter()
  const checkout = useRef(createCheckout())
  const [coupons, setCoupons] = useState<Coupon[]>([])
  const [couponId, setCouponId] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState<UnavailableItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    listCoupons(shopSlug).then(setCoupons, () => setCoupons([]))
  }, [shopSlug])

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
      setError(describeError(caught))
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
            router.push(`/${shopSlug}/orders/${result.order.id}`)
          } finally {
            setSubmitting(false)
          }
        })
      }
    />
  )
}
