export type Locale = 'zh-CN' | 'en-US'
export const LOCALE_COOKIE = 'shop_locale'
export function resolveLocale(cookieValue: string | undefined, acceptLanguage: string | null | undefined): Locale {
  if (cookieValue === 'zh-CN' || cookieValue === 'en-US') return cookieValue
  const languages = (acceptLanguage ?? '').split(',').map((item, index) => {
    const [tag, quality] = item.trim().toLowerCase().split(';')
    const q = quality ? Number(quality.trim().replace(/^q=/, '')) : 1
    return { tag: tag ?? '', q, index }
  }).filter(({ q }) => Number.isFinite(q) && q > 0 && q <= 1).sort((a, b) => b.q - a.q || a.index - b.index)
  for (const { tag } of languages) {
    if (/^en(?:-[a-z]+)*$/.test(tag)) return 'en-US'
    if (/^zh(?:-[a-z]+)*$/.test(tag)) return 'zh-CN'
  }
  return 'zh-CN'
}
