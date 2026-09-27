'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSession } from '@/api/credentials'
import { ApiError } from '@/api/errors'
import { getCart } from '@/api/shopApi'
import type { Cart } from '@/types/shop'
import { ShopContext, type ShopContextValue } from './ShopContext'
import { bindDemoCustomer, openShopSession, switchDemoIdentity } from './sessionService'

type Phase = 'opening' | 'ready' | 'unavailable' | 'error'

/**
 * 店铺外壳：进入 `/{shop_slug}` 时创建访客会话（只存内存），顶栏展示身份与购物车角标。
 * 公开页面（店铺页、商品详情）由服务端渲染并作为 children 传入，会话只影响这层外壳。
 */
export function ShopShell({ shopSlug, children }: { shopSlug: string; children: ReactNode }) {
  const session = useSession()
  const pathname = usePathname()
  const [phase, setPhase] = useState<Phase>('opening')
  const [cart, setCart] = useState<Cart | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refreshCart = useCallback(async () => {
    setCart(await getCart())
  }, [])

  useEffect(() => {
    let cancelled = false
    openShopSession(shopSlug)
      .then(async () => {
        if (cancelled) return
        setPhase('ready')
        await refreshCart().catch(() => undefined)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        // 未知或未开放的店铺统一 403：不区分「不存在」与「未开放」。
        setPhase(error instanceof ApiError && error.status === 403 ? 'unavailable' : 'error')
      })
    return () => {
      cancelled = true
    }
  }, [shopSlug, refreshCart])

  const value = useMemo<ShopContextValue>(
    () => ({
      shopSlug,
      session,
      cart,
      refreshCart,
      setCart,
      bindDemoCustomer: async () => {
        const result = await bindDemoCustomer()
        if (result.cartAdjusted) setNotice('部分商品因售罄或数量上限已调整。')
        await refreshCart()
        return result
      },
      switchIdentity: async () => {
        await switchDemoIdentity(shopSlug)
        setNotice(null)
        await refreshCart().catch(() => undefined)
      },
    }),
    [shopSlug, session, cart, refreshCart],
  )

  // 头部按钮没有别的调用方来接住异常：演示身份入口只在演示部署开放，失败要给出提示。
  async function fromHeader(action: () => Promise<unknown>) {
    try {
      await action()
    } catch {
      setNotice('演示身份暂不可用，请稍后重试。')
    }
  }

  const base = `/${shopSlug}`
  const links = [
    { href: base, label: '店铺' },
    { href: `${base}/assistant`, label: '导购助手' },
    { href: `${base}/cart`, label: '购物车' },
  ]
  const cartCount = cart?.items.length ?? 0

  return (
    <ShopContext.Provider value={value}>
      <header className="topbar">
        <Link href={base} className="brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/borough-logo.svg" alt="" width={24} height={24} />
          Borough
        </Link>
        <nav aria-label="店铺导航">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={pathname === link.href ? 'page' : undefined}
            >
              {link.label}
              {link.href.endsWith('/cart') && cartCount > 0 ? (
                <span className="badge" aria-label={`购物车 ${cartCount} 件商品`}>
                  {cartCount}
                </span>
              ) : null}
            </Link>
          ))}
        </nav>
        <div className="row">
          <span className="muted" data-testid="identity">
            {session?.isBound ? '演示顾客' : '访客'}
          </span>
          {session?.isBound ? (
            <button className="btn" onClick={() => void fromHeader(value.switchIdentity)}>
              退出演示身份
            </button>
          ) : session ? (
            <button className="btn" onClick={() => void fromHeader(value.bindDemoCustomer)}>
              绑定演示顾客
            </button>
          ) : null}
        </div>
      </header>
      <main className="page">
        {notice ? (
          <p className="notice" role="status">
            {notice}
          </p>
        ) : null}
        {phase === 'unavailable' ? (
          <p className="notice notice-error" role="alert">
            该店铺不存在或暂未开放。
          </p>
        ) : phase === 'error' ? (
          <p className="notice notice-error" role="alert">
            暂时无法连接服务，请稍后重试。
          </p>
        ) : (
          children
        )}
        <p className="muted" style={{ marginTop: 32 }}>
          演示环境：身份为演示身份，非真实登录；结账与支付均为演示，不产生真实扣款。
        </p>
      </main>
    </ShopContext.Provider>
  )
}
