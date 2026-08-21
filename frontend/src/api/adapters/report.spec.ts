import { describe, expect, it } from 'vitest'

import { toDailyReport } from './report'

describe('toDailyReport', () => {
  it('将日报 snake_case 载荷转换为组件领域模型', () => {
    const report = toDailyReport({
      answer_id: '00000000-0000-0000-0000-000000000001',
      report_date: '2026-08-20',
      metrics: [{ metric_code: 'gmv', display_name: '成交 GMV', unit: '元', value: '200.00' }],
      suggestions: ['建议一', '建议二'],
      degraded: false,
      degraded_reason: null,
    })

    expect(report.answerId).toBe('00000000-0000-0000-0000-000000000001')
    expect(report.metrics[0]).toEqual({
      code: 'gmv',
      displayName: '成交 GMV',
      unit: '元',
      value: '200.00',
    })
    expect(report.degradedReason).toBeUndefined()
  })
})
