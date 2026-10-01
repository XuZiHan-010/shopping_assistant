/**
 * 商品页与库存页共用的商品展示映射（W Task 10 从 `CatalogView.vue` 抽出）。
 *
 * - 商品状态 → 胶囊色调；界面文案键 `catalogPage.status.*`，未知状态原样显示；
 * - 契约 §8.12.3 `missing_content_fields` 的两个已知取值 → 界面文案键
 *   `catalogPage.contentField.*`，其他值与类目属性名一样保持后端原文。
 *
 * 缺口本身由后端按类目规则确定性计算，这里只做翻译与着色，不判定缺口（R4/R7）。
 */
import type { PillTone } from '@/components/layout/pillTone'

export const PRODUCT_STATUS_TONES: Readonly<Record<string, PillTone>> = {
  ONLINE: 'ok',
  OFFLINE: 'muted',
  AUDITING: 'info',
  REJECTED: 'warn',
}

export const CONTENT_FIELD_KEYS: Readonly<Record<string, 'description' | 'images'>> = {
  商品描述: 'description',
  商品图片: 'images',
}

export function isKnownProductStatus(value: string): boolean {
  return value in PRODUCT_STATUS_TONES
}

export function productStatusTone(value: string): PillTone {
  return PRODUCT_STATUS_TONES[value] ?? 'muted'
}
