import type { Locale } from './locale'

export type CategoryTone = 'dress' | 'shirt' | 'boot' | 'home' | 'beauty'

/**
 * 商品类目固定词表：后端只下发源值（契约 §8.8.1 `category`，不翻译）。
 * 英文与后端 `app/localization/catalog.py` 的确定性词典一致；未登记的类目原样显示、不上色。
 */
const categories: Record<string, { en: string; tone: CategoryTone }> = {
  女装: { en: "Women's wear", tone: 'dress' },
  男装: { en: "Men's wear", tone: 'shirt' },
  鞋靴: { en: 'Shoes', tone: 'boot' },
  家居: { en: 'Home goods', tone: 'home' },
  美妆: { en: 'Beauty', tone: 'beauty' },
}

export function categoryLabel(category: string, locale: Locale): string {
  return locale === 'en-US' ? categories[category]?.en ?? category : category
}

export function categoryTone(category: string | undefined): CategoryTone | undefined {
  return category ? categories[category]?.tone : undefined
}
