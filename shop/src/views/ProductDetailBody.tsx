'use client'

import { useRouter } from 'next/navigation'
import { AddToCartButton } from '@/components/AddToCartButton'
import { StockBadge } from '@/components/StockBadge'
import { TranslationNote } from '@/components/TranslationNote'
import { useChat } from '@/chat/ChatProvider'
import { categoryLabel } from '@/i18n/categories'
import { translate } from '@/i18n/LocaleProvider'
import { messages } from '@/i18n/messages'
import { formatPrice } from '@/lib/format'
import type { ProductDetail, ProductLocale } from '@/types/shop'
import { ProductArt } from './ProductArt'
import './storefront-views.css'

const translatedName: Record<string, 'attr.origin' | 'attr.material' | 'attr.size' | 'attr.shelfLife'> = {
  产地: 'attr.origin', 材质: 'attr.material', 尺码: 'attr.size', 保质期: 'attr.shelfLife',
}

export function ProductDetailBody({ product, shopSlug, onAsk }: { product: ProductDetail; shopSlug: string; onAsk?: () => void }) {
  const locale: ProductLocale = product.requestedLocale
  const copy = messages[locale]
  const t = (key: Parameters<typeof translate>[1], vars?: Record<string, string | number>) => translate(locale, key, vars)
  const { send } = useChat()
  const router = useRouter()
  const visibleName = (name: string) => locale === 'en-US' && translatedName[name] ? copy[translatedName[name]] : name
  async function ask(question: string) {
    onAsk?.()
    router.push(`/${encodeURIComponent(shopSlug)}`)
    await send(question)
  }
  return <article className="ws-product-body">
    <ProductArt src={product.imageUrl} alt={product.name} category={product.category} size={800} className="ws-product-art" />
    <div className="ws-product-info">
      <p className="ws-product-category">{categoryLabel(product.category, locale)}</p>
      <h1>{product.name}<TranslationNote status={product.nameTranslationStatus} locale={locale} /></h1>
      <div className="ws-product-price"><strong>{formatPrice(product.priceCents)}</strong><StockBadge band={product.stockBand} locale={locale} /></div>
      <p className="ws-product-lead">{product.shortDescription}<TranslationNote status={product.shortDescriptionTranslationStatus} locale={locale} /></p>
      <div className="ws-product-actions"><AddToCartButton productId={product.id} soldOut={product.stockBand === 'OUT_OF_STOCK'} locale={locale} /><button className="ws-ghost" onClick={() => void ask(t('product.askAbout', { name: product.name }))}>{copy.askClerk}</button></div>
      <section className="ws-product-attributes" aria-label={t('product.attributes')}><h2>{t('product.attributes')}</h2><dl>
        {product.attributes.filter(attribute => !product.missingAttributes.includes(attribute.name)).map(attribute => <div key={attribute.name}><dt>{attribute.name}<TranslationNote status={attribute.nameTranslationStatus} locale={locale} /></dt><dd>{attribute.value?.trim() || t('product.notProvided')}{attribute.value?.trim() && <TranslationNote status={attribute.valueTranslationStatus} locale={locale} />}{attribute.value?.trim() && attribute.source === 'DEMO' && <span className="pill pill-warn">{t('product.demoData')}</span>}</dd></div>)}
        {product.missingAttributes.map(name => <div key={`missing-${name}`}><dt>{visibleName(name)}</dt><dd className="ws-product-gap">{copy.gapProvide} · <button onClick={() => void ask(t('product.askGap', { name: product.name, attr: visibleName(name) }))}>{copy.askAboutIt} · {visibleName(name)}</button></dd></div>)}
      </dl></section>
      <section className="ws-product-description" aria-label={t('product.description')}><h2>{t('product.description')}</h2><p>{product.description}<TranslationNote status={product.descriptionTranslationStatus} locale={locale} /></p></section>
    </div>
  </article>
}
