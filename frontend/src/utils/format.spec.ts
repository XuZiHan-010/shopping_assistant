import { describe, expect, it } from 'vitest'

import { formatCell, toNumber } from './format'

describe('toNumber', () => {
  it('保留合法的零值，拒绝空值和不可解析值', () => {
    expect(toNumber('0')).toBe(0)
    expect(toNumber(0)).toBe(0)
    expect(toNumber('')).toBeNull()
    expect(toNumber('not-a-number')).toBeNull()
    expect(toNumber(null)).toBeNull()
  })
})

describe('formatCell', () => {
  it('以用户可读的方式展示空值、金额、日期和布尔值', () => {
    expect(formatCell(null)).toBe('—')
    expect(formatCell('128000.50', '元')).toBe('128,000.5 元')
    expect(formatCell('2026-08-07T12:30:00Z')).toBe('2026-08-07')
    expect(formatCell(true)).toBe('是')
    expect(formatCell(false)).toBe('否')
  })

  it('不会让超长 JSON 撑破单元格', () => {
    const value = JSON.stringify({ note: 'x'.repeat(500) })

    expect(formatCell(value)).toHaveLength(161)
    expect(formatCell(value)).toMatch(/…$/)
  })
})
