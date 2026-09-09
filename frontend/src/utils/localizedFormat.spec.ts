import { describe, expect, it } from 'vitest'

import { formatCurrency, formatDate, formatNumber } from './localizedFormat'

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
