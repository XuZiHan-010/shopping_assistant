import { STOCK_BAND_LABEL } from '@/lib/format'
import type { ProductLocale, StockBand } from '@/types/shop'

const TONE: Record<StockBand, string> = {
  IN_STOCK: 'pill-ok',
  LOW_STOCK: 'pill-warn',
  OUT_OF_STOCK: 'pill-off',
}

/** 库存只显示三档，不显示数量（D5）。 */
const EN_LABEL: Record<StockBand, string> = {
  IN_STOCK: 'In stock', LOW_STOCK: 'Low stock', OUT_OF_STOCK: 'Sold out',
}

export function StockBadge({ band, locale = 'zh-CN' }: { band: StockBand; locale?: ProductLocale }) {
  return <span className={`pill ${TONE[band]}`}>{locale === 'en-US' ? EN_LABEL[band] : STOCK_BAND_LABEL[band]}</span>
}
