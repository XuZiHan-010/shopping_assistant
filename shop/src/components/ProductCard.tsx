import Link from 'next/link'
import { formatPrice } from '@/lib/format'
import type { Product } from '@/types/shop'
import { StockBadge } from './StockBadge'
import { TranslationNote } from './TranslationNote'

export function ProductCard({ shopSlug, product }: { shopSlug: string; product: Product }) {
  return (
    <article className="card">
      <div className="card-body">
        <h3>
          <Link href={`/${shopSlug}/products/${product.id}`}>{product.name}</Link>
          <TranslationNote status={product.nameTranslationStatus} locale={product.requestedLocale} />
        </h3>
        <p className="muted">{product.shortDescription}<TranslationNote status={product.shortDescriptionTranslationStatus} locale={product.requestedLocale} /></p>
        <div className="row spread">
          <span className="price">{formatPrice(product.priceCents)}</span>
          <StockBadge band={product.stockBand} locale={product.requestedLocale} />
        </div>
      </div>
    </article>
  )
}
