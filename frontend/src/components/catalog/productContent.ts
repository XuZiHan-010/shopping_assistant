/**
 * 商品页与库存页共用的商品展示映射（W Task 10 从 `CatalogView.vue` 抽出）。
 *
 * - 商品状态 → 胶囊色调；界面文案键 `catalogPage.status.*`，未知状态原样显示；
 * - 契约 §8.12.3 `missing_content_fields` 的两个已知取值 → 界面文案键
 *   `catalogPage.contentField.*`，其他值与类目属性名一样保持后端原文。
 *
 * 缺口本身由后端按类目规则确定性计算，这里只做翻译与着色，不判定缺口（R4/R7）。
 */
import { resolveShopBaseUrl } from '@/api/client'
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

/**
 * 后端下发的受控图片地址 → `<img src>`。
 *
 * 演示图是顾客端站点的静态资源（`/demo/products/NN.webp`），商家端镜像里没有这些文件，
 * 所以相对路径拼到 `VITE_SHOP_BASE_URL` 上；未配置时返回 `null` 显示占位，不回退同源去拿 404。
 * 其余只放行 HTTPS 绝对地址（后端已按白名单过滤），别的形态一律不渲染。
 */
export function resolveProductImageSrc(
  imageUrl: string | null,
  shopBaseUrl: string | undefined = resolveShopBaseUrl(),
): string | null {
  if (!imageUrl) return null
  if (imageUrl.startsWith('/') && !imageUrl.startsWith('//')) {
    return shopBaseUrl ? `${shopBaseUrl}${imageUrl}` : null
  }
  return imageUrl.startsWith('https://') ? imageUrl : null
}

export function isKnownProductStatus(value: string): boolean {
  return value in PRODUCT_STATUS_TONES
}

export function productStatusTone(value: string): PillTone {
  return PRODUCT_STATUS_TONES[value] ?? 'muted'
}
