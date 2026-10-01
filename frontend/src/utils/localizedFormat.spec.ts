import { describe, expect, it } from 'vitest'

import {
  formatCurrency,
  formatDate,
  formatMoneyCents,
  formatNumber,
  formatRatioBp,
} from './localizedFormat'

describe('formatDate', () => {
  it('renders an English medium date for a date-only ISO string', () => {
    expect(formatDate('2026-08-31', 'en-US')).toContain('Aug')
  })

  it('renders a Chinese medium date for a date-only ISO string', () => {
    expect(formatDate('2026-08-31', 'zh-CN')).toContain('2026')
    expect(formatDate('2026-08-31', 'zh-CN')).not.toContain('Aug')
  })

  it('additionally renders the time when the input carries a time component', () => {
    expect(formatDate('2026-08-31T12:30:00Z', 'en-US')).toMatch(/\d{1,2}:\d{2}/)
  })

  it('does not invent a 00:00 time for a date-only input', () => {
    expect(formatDate('2026-08-31', 'en-US')).not.toMatch(/\d{1,2}:\d{2}/)
  })

  it('falls back to the raw value for an unparsable date', () => {
    expect(formatDate('not-a-date', 'en-US')).toBe('not-a-date')
  })
})

describe('formatNumber', () => {
  it('uses zh-CN thousand separators', () => {
    expect(formatNumber(1234.5, 'zh-CN')).toBe('1,234.5')
  })

  it('uses en-US thousand separators', () => {
    expect(formatNumber(1234.5, 'en-US')).toBe('1,234.5')
  })

  it('caps at two fraction digits', () => {
    expect(formatNumber(1234.567, 'en-US')).toBe('1,234.57')
  })
})

describe('formatCurrency', () => {
  it('renders CNY with a CN¥/CNY marker in English mode', () => {
    expect(formatCurrency(1234.5, 'en-US', 'CNY')).toMatch(/CN¥|CNY/)
  })

  it('defaults the currency to CNY when not given', () => {
    expect(formatCurrency(1234.5, 'zh-CN')).toContain('¥')
  })
})

describe('formatRatioBp', () => {
  it('converts basis points (1/10000) to a percentage string', () => {
    expect(formatRatioBp(2000, 'en-US')).toBe('20%')
  })

  it('keeps one fraction digit by default for non-round values', () => {
    expect(formatRatioBp(1234, 'en-US')).toBe('12.3%')
  })

  it('supports negative basis points (contribution can be negative)', () => {
    expect(formatRatioBp(-500, 'en-US')).toBe('-5%')
  })

  it('returns null as-is instead of inventing 0% for missing data', () => {
    expect(formatRatioBp(null, 'en-US')).toBeNull()
  })

  it('respects a custom maximumFractionDigits', () => {
    expect(formatRatioBp(1234, 'en-US', { maximumFractionDigits: 2 })).toBe('12.34%')
  })
})

describe('formatMoneyCents（W Task 8）', () => {
  it('把整数分按 locale 渲染成人民币金额，只换单位不取整', () => {
    expect(formatMoneyCents(1234567, 'zh-CN')).toBe('¥12,345.67')
    expect(formatMoneyCents(1234567, 'en-US')).toBe('CN¥12,345.67')
  })

  it('signed 时正数带加号、负数带减号、零不带符号', () => {
    expect(formatMoneyCents(3600, 'zh-CN', { signed: true })).toBe('+¥36.00')
    expect(formatMoneyCents(-71200, 'zh-CN', { signed: true })).toBe('-¥712.00')
    expect(formatMoneyCents(0, 'zh-CN', { signed: true })).toBe('¥0.00')
  })
})

describe('formatRatioBp（signed，W Task 8）', () => {
  it('signed 时带正负号，zh-CN 同样按万分比换算', () => {
    expect(formatRatioBp(1234, 'zh-CN', { signed: true })).toBe('+12.3%')
    expect(formatRatioBp(-504, 'zh-CN', { signed: true })).toBe('-5%')
    expect(formatRatioBp(0, 'zh-CN', { signed: true })).toBe('0%')
    expect(formatRatioBp(null, 'zh-CN', { signed: true })).toBeNull()
  })
})
