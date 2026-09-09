/**
 * 共享格式化工具：日期、数字和货币都显式接收 `locale`，不内置默认语言。
 *
 * 图表专属的格式化（ECharts axis/tooltip formatter 等）不在这里，留给
 * Task 10B/10D 在各自组件里按需实现；这里只覆盖跨页面复用的通用格式化。
 */
import type { SupportedLocale } from '@/i18n'

/** 粗略判断字符串是否带时间部分（如 `2026-08-31T12:30:00Z`），而不只是纯日期。 */
const HAS_TIME_PATTERN = /T\d{2}:\d{2}/

/**
 * 把 ISO 日期/日期时间字符串或 `Date` 格式化为界面展示用的本地化文本。
 * 纯日期输入（`2026-08-31`）只渲染日期，不臆造一个 00:00 的时间点；
 * 带时间部分的输入额外渲染时间。
 */
export function formatDate(value: string | Date, locale: SupportedLocale): string {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)

  const hasTime = value instanceof Date || HAS_TIME_PATTERN.test(value)
  const formatter = new Intl.DateTimeFormat(
    locale,
    hasTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' },
  )
  return formatter.format(date)
}

/** 按 `locale` 的千分位和小数习惯格式化数字，最多保留两位小数。 */
export function formatNumber(value: number, locale: SupportedLocale): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)
}

/**
 * 按 `locale` 格式化货币金额。`currency` 默认 `CNY`——经营数据的金额字段
 * 本身就是人民币，展示语言切换不改变货币单位本身，只改变数字的呈现习惯
 * 和货币符号的排版（例如英文界面下人民币显示为 `CN¥`）。
 */
export function formatCurrency(
  value: number,
  locale: SupportedLocale,
  currency = 'CNY',
): string {
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value)
}
