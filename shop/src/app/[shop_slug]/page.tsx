import { getStore, listCoupons, listProducts } from '@/api/catalogApi'
import { headers } from 'next/headers'
import { CouponList } from '@/components/CouponList'
import { ProductCard } from '@/components/ProductCard'
import { orNotFound } from './serverData'

// 公开页面服务端渲染（无鉴权，利于首屏）；库存与价格随时变化，不做静态缓存。
export const dynamic = 'force-dynamic'

export default async function StorePage({ params }: { params: Promise<{ shop_slug: string }> }) {
  const { shop_slug: shopSlug } = await params
  const acceptLanguage = (await headers()).get('accept-language') ?? undefined
  const [store, products, coupons] = await orNotFound(() =>
    Promise.all([getStore(shopSlug, acceptLanguage), listProducts(shopSlug, acceptLanguage), listCoupons(shopSlug)]),
  )
  const english = products[0]?.requestedLocale === 'en-US'
    || (products.length === 0 && acceptLanguage?.trim().toLowerCase().startsWith('en'))
  const locale = english ? 'en-US' : 'zh-CN'

  return (
    <div className="stack">
      <header className="stack" style={{ gap: 8 }}>
        <h1>{store.displayName}</h1>
        <p className="muted">{store.rulesSummary}</p>
      </header>

      {coupons.length > 0 ? <CouponList coupons={coupons} locale={locale} /> : null}

      <section className="stack" aria-label={english ? 'Products for sale' : '在售商品'}>
        <h2>{english ? 'Products for sale' : '在售商品'}</h2>
        {products.length === 0 ? (
          <p className="muted">{english ? 'This store has no products for sale yet.' : '这家店暂时没有在售商品。'}</p>
        ) : (
          <div className="grid">
            {products.map((product) => (
              <ProductCard key={product.id} shopSlug={shopSlug} product={product} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
