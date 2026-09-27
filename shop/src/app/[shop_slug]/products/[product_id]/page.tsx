import { getProduct } from '@/api/catalogApi'
import { headers } from 'next/headers'
import { AddToCartButton } from '@/components/AddToCartButton'
import { AttributeTable } from '@/components/AttributeTable'
import { StockBadge } from '@/components/StockBadge'
import { TranslationNote } from '@/components/TranslationNote'
import { formatPrice } from '@/lib/format'
import { orNotFound } from '../../serverData'

export const dynamic = 'force-dynamic'

export default async function ProductPage({
  params,
}: {
  params: Promise<{ shop_slug: string; product_id: string }>
}) {
  const { shop_slug: shopSlug, product_id: productId } = await params
  const acceptLanguage = (await headers()).get('accept-language') ?? undefined
  const product = await orNotFound(() => getProduct(shopSlug, productId, acceptLanguage))
  const english = product.requestedLocale === 'en-US'

  return (
    <article className="stack">
      <header className="stack" style={{ gap: 8 }}>
        <h1>{product.name}<TranslationNote status={product.nameTranslationStatus} locale={product.requestedLocale} /></h1>
        <p className="muted">{product.shortDescription}<TranslationNote status={product.shortDescriptionTranslationStatus} locale={product.requestedLocale} /></p>
        <div className="row">
          <span className="price">{formatPrice(product.priceCents)}</span>
          <StockBadge band={product.stockBand} locale={product.requestedLocale} />
        </div>
        <AddToCartButton productId={product.id} soldOut={product.stockBand === 'OUT_OF_STOCK'} locale={product.requestedLocale} />
      </header>

      <section className="stack" aria-label={english ? 'Product description' : '商品介绍'}>
        <h2>{english ? 'Product description' : '商品介绍'}</h2>
        <p style={{ whiteSpace: 'pre-wrap' }}>{product.description}<TranslationNote status={product.descriptionTranslationStatus} locale={product.requestedLocale} /></p>
      </section>

      <section className="stack" aria-label={english ? 'Product attributes' : '商品属性'}>
        <h2>{english ? 'Product attributes' : '商品属性'}</h2>
        <AttributeTable attributes={product.attributes} locale={product.requestedLocale} />
      </section>
    </article>
  )
}
