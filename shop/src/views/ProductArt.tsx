'use client'

import { useState } from 'react'
import Image from 'next/image'
import { categoryTone } from '@/i18n/categories'
import { useLocale } from '@/i18n/LocaleProvider'
import { messages } from '@/i18n/messages'
import type { ProductLocale } from '@/types/shop'
import styles from './ProductArt.module.css'

type ProductArtProps = {
  product?: { name: string; imageUrl: string | null; category?: string }
  /** 类目源值；图片加载前按类目上底色（缺图仍是虚线条纹）。 */
  category?: string
  src?: string | null
  alt?: string
  size: number | 'thumb' | 'tile'
  locale?: ProductLocale
  className?: string
}

export function ProductArt({ product, src, alt, category, size, locale, className = '' }: ProductArtProps) {
  const { locale: currentLocale } = useLocale()
  const imageSrc = product ? product.imageUrl : (src ?? null)
  const imageAlt = product ? product.name : (alt ?? '')
  const dimension = typeof size === 'number' ? size : size === 'thumb' ? 96 : 800
  const compact = size === 'thumb' || (typeof size === 'number' && size <= 96)
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const failed = !imageSrc || failedSrc === imageSrc
  const tone = categoryTone(category ?? product?.category)
  return <span className={`${styles.art} ${compact ? styles.thumb : ''} ${failed ? styles.empty : ''} ${className}`} data-cat={tone}>
    {failed ? <span>{messages[locale ?? currentLocale].noImage}</span> : <Image src={imageSrc} alt={imageAlt} width={dimension} height={dimension} unoptimized onError={() => setFailedSrc(imageSrc)} />}
  </span>
}
