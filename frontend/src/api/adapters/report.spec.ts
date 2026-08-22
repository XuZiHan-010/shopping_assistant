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

  it('降级时如实转出原因，不得用空指标伪装成有数据', () => {
    const report = toDailyReport({
      answer_id: '00000000-0000-0000-0000-000000000002',
      report_date: '2026-08-20',
      metrics: [],
      suggestions: ['近 7 日退款压力较低，可以继续保持履约和售后响应稳定。'],
      degraded: true,
      degraded_reason: '查询失败，暂无法生成经营数据摘要',
    })

    expect(report.degraded).toBe(true)
    expect(report.degradedReason).toBe('查询失败，暂无法生成经营数据摘要')
    expect(report.metrics).toEqual([])
  })
})
