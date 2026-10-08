'use client'

import type { UnavailableItem } from '@/checkout/checkout'
import { useLocale } from '@/i18n/LocaleProvider'
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
  const { t, locale } = useLocale()
  const { session, cart, coupons, couponId, unavailable, error, submitting } = props
  const isBound = session?.isBound === true
  const items = cart?.items ?? []
  const nameOf = (productId: string) => items.find((i) => i.productId === productId)?.name ?? '商品'

  return (
    <div className="stack">
      <h1>{t('cart')}</h1>

      {!isBound ? (
        <div className="notice" role="note">
          <p style={{ margin: 0 }}>
            {t('cartUnbound')}
          </p>
          <p className="muted" style={{ margin: '8px 0 0' }}>
            {t('notReal')}
          </p>
          <button className="btn" style={{ marginTop: 8 }} onClick={props.onBind}>
            {t('bind')}
          </button>
        </div>
      ) : null}

      {unavailable.length > 0 ? (
        <div className="notice notice-error" role="alert">
          <strong>{t('cartUnavailable')}</strong>
          {unavailable.map((entry) => (
            <p key={entry.productId} style={{ margin: '4px 0 0' }}>
              {nameOf(entry.productId)}：{locale === 'en-US' ? entry.reason.replaceAll('_', ' ').toLowerCase() : UNAVAILABLE_LABEL[entry.reason]}
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
        <p className="muted">{t('cartEmpty')} {t('cartEmptyHint')}</p>
      ) : (
        <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {items.map((item) => (
            <li key={item.productId} className="card card-body">
              <div className="row spread">
                <strong>{item.name}</strong>
                <StockBadge band={item.stockBand} />
              </div>
              <div className="row spread">
                <span className="muted">{t('unit', { p: formatPrice(item.unitPriceCents) })}</span>
                <span className="price">{formatPrice(item.lineTotalCents)}</span>
              </div>
              <div className="row">
                <label>
                  <span className="muted">{t('items', { n: item.quantity })} </span>
                  <input
                    type="number"
                    min={1}
                    aria-label={t('quantityLabel', { name: item.name })}
                    value={item.quantity}
                    onChange={(event) => {
                      const next = Number(event.target.value)
                      if (Number.isInteger(next) && next >= 1) props.onQuantityChange(item.productId, next)
                    }}
                  />
                </label>
                <button className="btn" onClick={() => props.onRemove(item.productId)}>
                  {t('remove')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {items.length > 0 ? (
        <section className="card card-body" aria-label={t('checkoutLabel')}>
          {coupons.length > 0 ? (
            <label className="row">
              <span>{t('coupon')}</span>
              <select
                value={couponId ?? ''}
                onChange={(event) => props.onCouponChange(event.target.value || null)}
              >
                <option value="">{t('noCoupon')}</option>
                {coupons.map((coupon) => (
                  <option key={coupon.id} value={coupon.id}>
                    {coupon.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="row spread">
            <span>{t('subtotal')}</span>
            <span className="price">{formatPrice(cart?.subtotalCents ?? 0)}</span>
          </div>
          <p className="muted" style={{ margin: 0 }}>
            {t('calcNote')}
          </p>
          <p className="notice notice-demo" style={{ margin: 0 }}>
            {t('demoNote')}
          </p>
          <button
            className="btn btn-primary"
            disabled={!isBound || submitting}
            onClick={props.onSubmit}
          >
            {t('submit')}
          </button>
        </section>
      ) : null}
    </div>
  )
}
