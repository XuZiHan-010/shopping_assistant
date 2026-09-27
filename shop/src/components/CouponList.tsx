import { formatPrice } from '@/lib/format'
import type { Coupon, ProductLocale } from '@/types/shop'

function describe(coupon: Coupon, locale: ProductLocale): string {
  if (locale === 'en-US') {
    const threshold = coupon.minSpendCents > 0 ? `Spend ${formatPrice(coupon.minSpendCents)}, ` : ''
    if (coupon.kind === 'AMOUNT_OFF' && coupon.amountOffCents !== null) {
      return `${threshold}save ${formatPrice(coupon.amountOffCents)}`
    }
    if (coupon.discountBps !== null) return `${threshold}get ${coupon.discountBps / 100}% off`
    return coupon.name
  }
  const threshold = coupon.minSpendCents > 0 ? `满 ${formatPrice(coupon.minSpendCents)} ` : ''
  if (coupon.kind === 'AMOUNT_OFF' && coupon.amountOffCents !== null) {
    return `${threshold}减 ${formatPrice(coupon.amountOffCents)}`
  }
  if (coupon.discountBps !== null) return `${threshold}享 ${coupon.discountBps / 100}% 优惠`
  return coupon.name
}

/** 只展示后端返回的、当前已生效的券；实际减免由后端在下单时计算。 */
export function CouponList({ coupons, locale = 'zh-CN' }: { coupons: Coupon[]; locale?: ProductLocale }) {
  return (
    <section className="stack" aria-label={locale === 'en-US' ? 'Available coupons' : '可用优惠券'}>
      <h2>{locale === 'en-US' ? 'Available coupons' : '可用优惠券'}</h2>
      <ul className="row" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {coupons.map((coupon) => (
          <li key={coupon.id} className="card card-body">
            <strong>{coupon.name}</strong>
            {locale === 'en-US' ? <span className="muted">Original coupon name</span> : null}
            <span className="muted">{describe(coupon, locale)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
