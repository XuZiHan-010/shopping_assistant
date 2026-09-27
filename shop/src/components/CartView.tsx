'use client'

import type { UnavailableItem } from '@/checkout/checkout'
import { formatPrice } from '@/lib/format'
import { UNAVAILABLE_LABEL } from '@/lib/labels'
import type { ShopSession } from '@/types/session'
import type { Cart, Coupon } from '@/types/shop'
import { StockBadge } from './StockBadge'

export interface CartViewProps {
  session: ShopSession | null
  cart: Cart | null
  coupons: Coupon[]
  couponId: string | null
  /** 提交订单被后端拒绝时逐项列出的不可用项；购物车行本身不会被移除。 */
  unavailable: UnavailableItem[]
  error: string | null
  submitting: boolean
  onCouponChange: (couponId: string | null) => void
  onQuantityChange: (productId: string, quantity: number) => void
  onRemove: (productId: string) => void
  onSubmit: () => void
  onBind: () => void
}

/**
 * 购物车与结账（C3、C4）。所有金额都来自后端响应，这里只做格式化展示：
 * 不求和、不乘单价、不算优惠。
 */
export function CartView(props: CartViewProps) {
  const { session, cart, coupons, couponId, unavailable, error, submitting } = props
  const isBound = session?.isBound === true
  const items = cart?.items ?? []
  const nameOf = (productId: string) => items.find((i) => i.productId === productId)?.name ?? '商品'

  return (
    <div className="stack">
      <h1>购物车</h1>

      {!isBound ? (
        <div className="notice" role="note">
          <p style={{ margin: 0 }}>
            未绑定身份时刷新后无法找回购物车；绑定演示身份后可恢复。
          </p>
          <p className="muted" style={{ margin: '8px 0 0' }}>
            演示身份，非真实登录。
          </p>
          <button className="btn" style={{ marginTop: 8 }} onClick={props.onBind}>
            绑定演示顾客
          </button>
        </div>
      ) : null}

      {unavailable.length > 0 ? (
        <div className="notice notice-error" role="alert">
          <strong>以下商品当前无法下单，请调整后重试：</strong>
          {unavailable.map((entry) => (
            <p key={entry.productId} style={{ margin: '4px 0 0' }}>
              {nameOf(entry.productId)}：{UNAVAILABLE_LABEL[entry.reason]}
            </p>
          ))}
        </div>
      ) : null}

      {error ? (
        <div className="notice notice-error" role="alert">
          {error}
        </div>
      ) : null}

      {items.length === 0 ? (
        <p className="muted">购物车还是空的，去店铺里逛逛，或者让导购助手帮你挑。</p>
      ) : (
        <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {items.map((item) => (
            <li key={item.productId} className="card card-body">
              <div className="row spread">
                <strong>{item.name}</strong>
                <StockBadge band={item.stockBand} />
              </div>
              <div className="row spread">
                <span className="muted">单价 {formatPrice(item.unitPriceCents)}</span>
                <span className="price">{formatPrice(item.lineTotalCents)}</span>
              </div>
              <div className="row">
                <label>
                  <span className="muted">数量 </span>
                  <input
                    type="number"
                    min={1}
                    aria-label={`${item.name} 数量`}
                    value={item.quantity}
                    onChange={(event) => {
                      const next = Number(event.target.value)
                      if (Number.isInteger(next) && next >= 1) props.onQuantityChange(item.productId, next)
                    }}
                  />
                </label>
                <button className="btn" onClick={() => props.onRemove(item.productId)}>
                  移除
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {items.length > 0 ? (
        <section className="card card-body" aria-label="结账">
          {coupons.length > 0 ? (
            <label className="row">
              <span>优惠券</span>
              <select
                value={couponId ?? ''}
                onChange={(event) => props.onCouponChange(event.target.value || null)}
              >
                <option value="">不使用</option>
                {coupons.map((coupon) => (
                  <option key={coupon.id} value={coupon.id}>
                    {coupon.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="row spread">
            <span>小计</span>
            <span className="price">{formatPrice(cart?.subtotalCents ?? 0)}</span>
          </div>
          <p className="muted" style={{ margin: 0 }}>
            优惠与应付金额以提交订单后后端计算的结果为准。
          </p>
          <p className="notice notice-demo" style={{ margin: 0 }}>
            演示结账，不产生真实扣款。
          </p>
          <button
            className="btn btn-primary"
            disabled={!isBound || submitting}
            onClick={props.onSubmit}
          >
            提交订单
          </button>
        </section>
      ) : null}
    </div>
  )
}
