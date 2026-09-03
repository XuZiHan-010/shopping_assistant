import { DEFAULT_LOCALE } from '@/i18n'

const EMPTY_CELL = '—'
const MAX_CELL_LENGTH = 160

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

export function formatCell(value: unknown, unit?: string): string {
  if (value === null || value === undefined || value === '') return EMPTY_CELL
  if (typeof value === 'boolean') return value ? '是' : '否'

  if (typeof value === 'string' && isIsoDate(value)) return value.slice(0, 10)

  const numeric = toNumber(value)
  if (numeric !== null) {
    // `formatCell` 本身还没有显式接收 locale 的调用方（DetailTable.vue /
    // MetricChartPanel.vue 属于 Task 10B 的改造范围），这里先把硬编码字面量
    // 换成消息目录的默认语言常量，不再有裸的 'zh-CN' 字符串；真正按当前
    // locale 显式格式化数字/日期/货币，见同目录下的 `localizedFormat.ts`。
    const formatted = new Intl.NumberFormat(DEFAULT_LOCALE, { maximumFractionDigits: 2 }).format(
      numeric,
    )
    return unit ? `${formatted} ${unit}` : formatted
  }

  if (typeof value === 'object') return truncate(JSON.stringify(value))
  return truncate(String(value))
}
