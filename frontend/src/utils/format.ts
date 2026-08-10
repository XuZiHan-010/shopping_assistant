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
    const formatted = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(numeric)
    return unit ? `${formatted} ${unit}` : formatted
  }

  if (typeof value === 'object') return truncate(JSON.stringify(value))
  return truncate(String(value))
}
