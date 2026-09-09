import { createI18n } from 'vue-i18n'

import type { MessageSchema } from './keys'
import { enUS } from './locales/en-US'
import { zhCN } from './locales/zh-CN'

/**
 * 与后端 `backend/app/localization/locales.py` 的 `SupportedLocale` 严格
 * 保持字面量一致——它会被当作 `Accept-Language` 派生的请求头值直接发给
 * 后端（Task 11），后端用 `parse_accept_language()` 解析，两边的字符串
 * 必须逐字节相同。
 */
export type SupportedLocale = 'zh-CN' | 'en-US'

export const DEFAULT_LOCALE: SupportedLocale = 'zh-CN'

export const SUPPORTED_LOCALES: readonly SupportedLocale[] = ['zh-CN', 'en-US']

// 显式给出第三个 Legacy=false 类型参数——只靠 `legacy: false` 这一个运行时
// 字段，`createI18n` 的重载在部分显式类型参数场景下仍可能推断不出字面量
// `false`，退回 Legacy 泛型默认值 `true`，导致 `i18n.global.locale` 被
// 推成普通字符串而不是 Composer 的 `Ref`。
export const i18n = createI18n<[MessageSchema], SupportedLocale, false>({
  legacy: false,
  locale: DEFAULT_LOCALE,
  fallbackLocale: DEFAULT_LOCALE,
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})
