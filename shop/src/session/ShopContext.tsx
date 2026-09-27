'use client'

import { createContext, useContext } from 'react'
import type { Cart } from '@/types/shop'
import type { BindResult, ShopSession } from '@/types/session'

export interface ShopContextValue {
  shopSlug: string
  session: ShopSession | null
  /** 最近一次从服务端 `GET /cart` 读到的购物车；角标与购物车页都以它为准。 */
  cart: Cart | null
  /** 重新向服务端拉取购物车。Agent 加购后靠它更新，不从回答文本里解析。 */
  refreshCart: () => Promise<void>
  setCart: (cart: Cart) => void
  bindDemoCustomer: () => Promise<BindResult>
  switchIdentity: () => Promise<void>
}

export const ShopContext = createContext<ShopContextValue | null>(null)

export function useShop(): ShopContextValue {
  const value = useContext(ShopContext)
  if (!value) throw new Error('useShop 必须在 ShopShell 内使用')
  return value
}
