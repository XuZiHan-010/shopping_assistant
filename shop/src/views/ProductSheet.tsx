'use client'

import { useEffect, useRef, useState } from 'react'
import { getProduct } from '@/api/catalogApi'
import { useLocale } from '@/i18n/LocaleProvider'
import type { ProductDetail } from '@/types/shop'
import { ProductDetailBody } from './ProductDetailBody'
import './storefront-views.css'

export function ProductSheet({ shopSlug, productId, onClose }: { shopSlug: string; productId: string; onClose: () => void }) {
  const { locale, t } = useLocale()
  const key = `${shopSlug}:${productId}:${locale}`
  const [loaded, setLoaded] = useState<{ key: string; product: ProductDetail | null; error: boolean }>({ key: '', product: null, error: false })
  const product = loaded.key === key ? loaded.product : null
  const error = loaded.key === key && loaded.error
  const closeRef = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef<HTMLElement | null>(null)
  useEffect(() => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeRef.current?.focus()
    return () => returnFocus.current?.focus()
  }, [])
  useEffect(() => {
    let active = true
    getProduct(shopSlug, productId, locale).then(value => { if (active) setLoaded({ key, product: value, error: false }) }).catch(() => { if (active) setLoaded({ key, product: null, error: true }) })
    return () => { active = false }
  }, [shopSlug, productId, locale, key])
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      onClose()
      returnFocus.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return <div className="ws-sheet-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <section className="ws-sheet" role="dialog" aria-modal="true" aria-label={product?.name ?? t('product.details')}>
      <button ref={closeRef} className="ws-sheet-close" aria-label={t('close')} onClick={onClose}>×</button>
      {error ? <p role="alert">{t('product.loadFailed')}</p> : product ? <ProductDetailBody product={product} shopSlug={shopSlug} onAsk={onClose} /> : <p>{t('loading')}</p>}
    </section>
  </div>
}
