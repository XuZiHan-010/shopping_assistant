import { describe, expect, it } from 'vitest'

import type { ChartSeries } from '@/types/chat'

import { summarizeChart, toChartOption, validateChartRows } from './chart'

const trendChart: ChartSeries = {
  enabled: true,
  type: 'LINE',
  allowedTypes: ['LINE'],
  title: '近 3 日成交 GMV',
  dimensionKey: 'business_date',
  metricKey: 'gmv',
  unit: '元',
  data: [
    { business_date: '2026-08-01', gmv: '0' },
    { business_date: '2026-08-02', gmv: '128.50' },
    { business_date: '2026-08-03', gmv: 'bad' },
  ],
}

describe('validateChartRows', () => {
  it('对缺字段和空数据给出可见降级理由，而不是抛错', () => {
    expect(validateChartRows({ ...trendChart, metricKey: undefined })).toEqual({
      renderable: false,
      reason: '图表字段缺失，无法绘制。',
    })
    expect(validateChartRows({ ...trendChart, data: [] })).toEqual({
      renderable: false,
      reason: '本次回答没有可视化数据。',
    })
  })
})

describe('toChartOption', () => {
  it('把 Decimal 字符串转换为数值，同时保留不可解析值形成折线断点', () => {
    const option = toChartOption(trendChart, 'LINE', false)

    expect(option?.series).toEqual([
      expect.objectContaining({
        type: 'line',
        data: [0, 128.5, null],
        connectNulls: false,
      }),
    ])
    expect(option?.animation).toBe(true)
  })

  it('拒绝后端未允许的图表类型', () => {
    expect(toChartOption(trendChart, 'PIE', false)).toBeUndefined()
  })
})

describe('summarizeChart', () => {
  it('饼图摘要只讲占比，不编造趋势或环比', () => {
    const summary = summarizeChart(
      {
        ...trendChart,
        allowedTypes: ['BAR', 'PIE'],
        type: 'BAR',
        dimensionKey: 'category',
        data: [
          { category: '食品', gmv: '60' },
          { category: '家居', gmv: '40' },
        ],
      },
      'PIE',
    )

    expect(summary.total).toBe(100)
    expect(summary.sentence).toContain('食品')
    expect(summary.sentence).not.toMatch(/趋势|环比/)
  })

  it('首点为零时不计算 Infinity 环比', () => {
    expect(summarizeChart(trendChart, 'LINE').sentence).not.toContain('Infinity')
  })
})
