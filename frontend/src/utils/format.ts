import type { SupportedLocale } from '@/i18n'

import { formatNumber } from './localizedFormat'

const EMPTY_CELL = '—'
const MAX_CELL_LENGTH = 160

// Intl 会把 -0 及四舍五入后归零的小负数输出成 "-0"。
const NEGATIVE_ZERO = /^-0(?:\.0+)?$/

const BOOLEAN_LABELS: Readonly<Record<SupportedLocale, { true: string; false: string }>> = {
  'zh-CN': { true: '是', false: '否' },
  'en-US': { true: 'Yes', false: 'No' },
}

export function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string' || value.trim() === '') return null

  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function isIsoDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value)
}

function truncate(value: string): string {
  return value.length > MAX_CELL_LENGTH ? `${value.slice(0, MAX_CELL_LENGTH)}…` : value
}

/**
 * 明细表/图表数据表单元格的展示格式化。`locale` 显式传入、不设默认值——
 * 与 `localizedFormat.ts` 同一约定（Task 10A），调用方是 `DetailTable.vue`
 * 和 `MetricChartPanel.vue`（Task 10B），按当前展示语言取布尔文案和数字
 * 千分位/小数点习惯。业务数据本身（订单号、金额数值、ISO 日期子串等）
 * 不做翻译，只格式化。
 */
export function formatCell(value: unknown, locale: SupportedLocale, unit?: string): string {
  if (value === null || value === undefined || value === '') return EMPTY_CELL
  if (typeof value === 'boolean')
    return value ? BOOLEAN_LABELS[locale].true : BOOLEAN_LABELS[locale].false

  if (typeof value === 'string' && isIsoDate(value)) return value.slice(0, 10)

  const numeric = toNumber(value)
  if (numeric !== null) {
    const formatted = formatNumber(numeric, locale)
    // 不使用兼容性较差的 signDisplay 选项，直接规范化渲染后的负零：
    // Intl 会把 -0 及四舍五入后归零的小负数输出成 "-0"（各 locale 一致）。
    const safe = NEGATIVE_ZERO.test(formatted) ? formatted.slice(1) : formatted
    return unit ? `${safe} ${unit}` : safe
  }

  if (typeof value === 'object') return truncate(JSON.stringify(value))
  return truncate(String(value))
}
