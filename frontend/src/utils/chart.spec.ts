import { describe, expect, it } from 'vitest'

import type { ChartSeries } from '@/types/chat'

import { chartTypeLabel, summarizeChart, toChartOption, validateChartRows } from './chart'

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
  it('对缺字段和空数据给出可见降级理由，而不是抛错（zh-CN）', () => {
    expect(validateChartRows({ ...trendChart, metricKey: undefined }, 'zh-CN')).toEqual({
      renderable: false,
      reason: '图表字段缺失，无法绘制。',
    })
    expect(validateChartRows({ ...trendChart, data: [] }, 'zh-CN')).toEqual({
      renderable: false,
      reason: '本次回答没有可视化数据。',
    })
  })

  it('en-US 下降级理由使用英文，而不是硬编码中文', () => {
    expect(validateChartRows({ ...trendChart, metricKey: undefined }, 'en-US')).toEqual({
      renderable: false,
      reason: 'Chart fields are missing, so the chart cannot be drawn.',
    })
    expect(validateChartRows({ ...trendChart, data: [] }, 'en-US')).toEqual({
      renderable: false,
      reason: 'This answer has no visualization data.',
    })
  })
})

describe('chartTypeLabel', () => {
  it('按 locale 返回图表类型切换按钮文案', () => {
    expect(chartTypeLabel('LINE', 'zh-CN')).toBe('折线图')
    expect(chartTypeLabel('LINE', 'en-US')).toBe('Line chart')
    expect(chartTypeLabel('PIE', 'en-US')).toBe('Pie chart')
  })
})

describe('toChartOption', () => {
  it('把 Decimal 字符串转换为数值，同时保留不可解析值形成折线断点', () => {
    const option = toChartOption(trendChart, 'LINE', false, 'zh-CN')

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
    expect(toChartOption(trendChart, 'PIE', false, 'zh-CN')).toBeUndefined()
  })

  it('tooltip.valueFormatter 和 yAxis.axisLabel.formatter 按 locale 格式化数字', () => {
    const zh = toChartOption(trendChart, 'LINE', false, 'zh-CN')
    const en = toChartOption(trendChart, 'LINE', false, 'en-US')

    const tooltipFormatter = zh?.tooltip.valueFormatter as (value: number) => string
    const enTooltipFormatter = en?.tooltip.valueFormatter as (value: number) => string
    expect(tooltipFormatter(1234.5)).toBe('1,234.5')
    expect(enTooltipFormatter(1234.5)).toBe('1,234.5')

    const axisLabel = zh?.yAxis?.axisLabel as { formatter: (value: number) => string }
    expect(axisLabel.formatter(2000)).toBe('2,000')
  })

  it('option.aria.label.description 读取当前 locale，且不是 DOM 属性——单测直接检查 option 对象', () => {
    const zh = toChartOption(trendChart, 'LINE', false, 'zh-CN')
    const en = toChartOption(trendChart, 'LINE', false, 'en-US')

    const zhAria = zh?.aria as { enabled: boolean; label: { description: string } }
    const enAria = en?.aria as { enabled: boolean; label: { description: string } }
    expect(zhAria.enabled).toBe(true)
    expect(zhAria.label.description).toContain('合计')
    // 图表 chrome 用词（"合计"/"为最高值"）必须换成英文；`元` 是后端提供的
    // 业务单位数据，不属于要翻译的 UI 文案，按 R9 的"技术字段原样保留"仍会
    // 出现在英文句子里，因此这里只断言中文 chrome 词消失，而不是断言整句
    // 不含任何 CJK 字符。
    expect(enAria.label.description).not.toMatch(/合计|为最高值|占比/)
    expect(enAria.label.description).toMatch(/Total/)
  })

  it('locale 改变时 option 是重新构建的新对象，不是原地复用', () => {
    const zh = toChartOption(trendChart, 'LINE', false, 'zh-CN')
    const en = toChartOption(trendChart, 'LINE', false, 'en-US')

    expect(zh).not.toBe(en)
    expect((zh?.aria as { label: { description: string } }).label.description).not.toBe(
      (en?.aria as { label: { description: string } }).label.description,
    )
  })
})

describe('summarizeChart', () => {
  it('饼图摘要只讲占比，不编造趋势或环比（zh-CN）', () => {
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
      'zh-CN',
    )

    expect(summary.total).toBe(100)
    expect(summary.sentence).toContain('食品')
    expect(summary.sentence).not.toMatch(/趋势|环比/)
  })

  it('en-US 下摘要句子是英文 chrome 文案，不泄露中文的"占比"措辞', () => {
    const summary = summarizeChart(
      {
        ...trendChart,
        unit: undefined,
        allowedTypes: ['BAR', 'PIE'],
        type: 'BAR',
        dimensionKey: 'category',
        data: [
          { category: 'Food', gmv: '60' },
          { category: 'Home', gmv: '40' },
        ],
      },
      'PIE',
      'en-US',
    )

    expect(summary.total).toBe(100)
    expect(summary.sentence).toContain('Food')
    expect(summary.sentence).toContain('accounts for')
    expect(summary.sentence).not.toMatch(/[一-龥]/)
  })

  it('首点为零时不计算 Infinity 环比', () => {
    expect(summarizeChart(trendChart, 'LINE', 'zh-CN').sentence).not.toContain('Infinity')
    expect(summarizeChart(trendChart, 'LINE', 'en-US').sentence).not.toContain('Infinity')
  })
})
