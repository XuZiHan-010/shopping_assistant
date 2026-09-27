import type { StockBand } from '@/types/shop'

/** 后端金额一律是「分」；这里只做展示格式化，不做任何金额运算。 */
export function formatPrice(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}

export const STOCK_BAND_LABEL: Record<StockBand, string> = {
  IN_STOCK: '有货',
  LOW_STOCK: '紧张',
  OUT_OF_STOCK: '售罄',
}

/** 按查看者时区换算（浏览器本地时区），来源时区另行展示（D14⑩）。 */
export function formatEventTime(iso: string, locale = 'zh-CN'): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(iso),
  )
}
