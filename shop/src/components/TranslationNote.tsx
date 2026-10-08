import type { ProductLocale, TranslationStatus } from '@/types/shop'

/** 译文状态独立于商品的 MERCHANT/DEMO 内容来源。 */
export function TranslationNote({ status, locale }: { status: TranslationStatus; locale: ProductLocale }) {
  if (status === 'SOURCE') return null
  const label = status === 'MACHINE'
    ? (locale === 'en-US' ? 'Machine translation' : '机器译文')
    : (locale === 'en-US' ? 'Original text · translation unavailable' : '暂无译文，显示原文')
  return <span className="pill pill-warn" style={{ marginLeft: 8 }}>{label}</span>
}
