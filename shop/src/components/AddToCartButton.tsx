'use client'

import { useState } from 'react'
import { setCartItem } from '@/api/shopApi'
import { useShop } from '@/session/ShopContext'
import type { ProductLocale } from '@/types/shop'

/** 加购：数量取服务端购物车里该商品当前的数量再加一；金额与库存判定都在后端。 */
export function AddToCartButton({ productId, soldOut, locale = 'zh-CN' }: { productId: string; soldOut: boolean; locale?: ProductLocale }) {
  const { cart, setCart, session } = useShop()
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function add() {
    setBusy(true)
    setMessage(null)
    try {
      const current = cart?.items.find((item) => item.productId === productId)?.quantity ?? 0
      setCart(await setCartItem(productId, current + 1))
      setMessage(locale === 'en-US' ? 'Added to cart' : '已加入购物车')
    } catch {
      setMessage(locale === 'en-US'
        ? 'Could not add to cart. The item may be sold out or the quantity limit was reached.'
        : '加入购物车失败，商品可能已售罄或数量已达上限。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="row">
      <button className="btn btn-primary" disabled={soldOut || busy || !session} onClick={() => void add()}>
        {locale === 'en-US' ? 'Add to cart' : '加入购物车'}
      </button>
      {message ? <span role="status" className="muted">{message}</span> : null}
    </div>
  )
}
