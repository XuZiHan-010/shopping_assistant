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
  it('以用户可读的方式展示空值、金额、日期和布尔值（zh-CN）', () => {
    expect(formatCell(null, 'zh-CN')).toBe('—')
    expect(formatCell('128000.50', 'zh-CN', '元')).toBe('128,000.5 元')
    expect(formatCell('2026-08-07T12:30:00Z', 'zh-CN')).toBe('2026-08-07')
    expect(formatCell(true, 'zh-CN')).toBe('是')
    expect(formatCell(false, 'zh-CN')).toBe('否')
  })

  it('en-US 下布尔值显示 Yes/No，而不是硬编码中文', () => {
    expect(formatCell(true, 'en-US')).toBe('Yes')
    expect(formatCell(false, 'en-US')).toBe('No')
    expect(formatCell('128000.50', 'en-US', 'yuan')).toBe('128,000.5 yuan')
    // 技术字段（ISO 日期子串）不随 locale 改变展示格式。
    expect(formatCell('2026-08-07T12:30:00Z', 'en-US')).toBe('2026-08-07')
  })

  it('不把负零或四舍五入归零的小负数显示成 -0', () => {
    expect(formatCell(-0, 'zh-CN')).toBe('0')
    expect(formatCell(-0.001, 'zh-CN', '元')).toBe('0 元')
  })

  it('保留真实负数的负号', () => {
    expect(formatCell(-1.5, 'zh-CN', '元')).toBe('-1.5 元')
    expect(formatCell(-1234.56, 'zh-CN')).toBe('-1,234.56')
  })

  it('不会让超长 JSON 撑破单元格', () => {
    const value = JSON.stringify({ note: 'x'.repeat(500) })

    expect(formatCell(value, 'zh-CN')).toHaveLength(161)
    expect(formatCell(value, 'zh-CN')).toMatch(/…$/)
  })
})
