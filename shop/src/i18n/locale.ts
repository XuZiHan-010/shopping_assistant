export type Locale = 'zh-CN' | 'en-US'
export const LOCALE_COOKIE = 'shop_locale'
/** 首访一律中文，不按浏览器 `Accept-Language` 协商（与商家端一致）；只有顾客在偏好设置里选过的语言才会改变它。 */
export function resolveLocale(cookieValue: string | undefined): Locale {
  return cookieValue === 'en-US' ? 'en-US' : 'zh-CN'
}
