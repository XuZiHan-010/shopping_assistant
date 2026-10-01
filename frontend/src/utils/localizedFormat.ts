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

/**
 * 把后端的万分比整数（`*_bp`，1/10000 为单位）格式化为百分比文本。
 *
 * Adapter 层保持 `*_bp` 为整数（不做浮点换算），换算只在这里发生：
 * `Intl.NumberFormat` 的 `style: 'percent'` 期望一个「1 = 100%」的小数，
 * 因此除以 10000（万分比换算成小数）。`null` 表示无可比数据，直接原样传回
 * `null`，调用方负责渲染「—」之类的占位符，不在这里编造 0%。
 */
export function formatRatioBp(
  valueBp: number | null,
  locale: SupportedLocale,
  options: { maximumFractionDigits?: number; signed?: boolean } = {},
): string | null {
  if (valueBp === null) return null
  return new Intl.NumberFormat(locale, {
    style: 'percent',
    maximumFractionDigits: options.maximumFractionDigits ?? 1,
    signDisplay: options.signed ? 'exceptZero' : 'auto',
  }).format(valueBp / 10000)
}

/**
 * 把后端的整数分（`*_cents`）格式化为人民币金额文本。只做「分 → 元」的单位换算，
 * 不取整、不参与任何业务计算；`signed` 用于贡献、变化这类有方向的金额（正数带 `+`）。
 */
export function formatMoneyCents(
  cents: number,
  locale: SupportedLocale,
  options: { signed?: boolean } = {},
): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: 'CNY',
    signDisplay: options.signed ? 'exceptZero' : 'auto',
  }).format(cents / 100)
}
