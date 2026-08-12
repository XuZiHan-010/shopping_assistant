import type { ChartSeries } from '@/types/chat'

import { toNumber } from './format'

export type ChartType = 'LINE' | 'BAR' | 'PIE'

export interface ChartValidation {
  renderable: boolean
  reason?: string
}

export interface ChartOption {
  animation: boolean
  tooltip: Record<string, unknown>
  legend?: Record<string, unknown>
  xAxis?: Record<string, unknown>
  yAxis?: Record<string, unknown>
  series: Array<Record<string, unknown>>
}

export interface ChartSummary {
  total: number
  sentence: string
}

export const SUPPORTED_TYPES: readonly ChartType[] = ['LINE', 'BAR', 'PIE']

export const CHART_TYPE_LABELS: Readonly<Record<ChartType, string>> = {
  LINE: '折线图',
  BAR: '柱状图',
  PIE: '饼图',
}

function isSupportedType(value: string): value is ChartType {
  return SUPPORTED_TYPES.includes(value as ChartType)
}

function points(chart: ChartSeries): Array<{ label: string; value: number | null }> {
  const dimensionKey = chart.dimensionKey
  const metricKey = chart.metricKey
  if (!dimensionKey || !metricKey) return []

  return chart.data.map((row) => ({
    label: String(row[dimensionKey] ?? '—'),
    value: toNumber(row[metricKey]),
  }))
}

function displayLabel(value: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(5, 10) : value
}

export function validateChartRows(chart?: ChartSeries): ChartValidation {
  if (!chart?.enabled || chart.data.length === 0) {
    return { renderable: false, reason: '本次回答没有可视化数据。' }
  }
  if (!chart.dimensionKey || !chart.metricKey) {
    return { renderable: false, reason: '图表字段缺失，无法绘制。' }
  }
  if (!chart.allowedTypes.some(isSupportedType)) {
    return { renderable: false, reason: '图表类型暂不支持。' }
  }
  return { renderable: true }
}

export function toChartOption(
  chart: ChartSeries,
  type: ChartType,
  reducedMotion: boolean,
): ChartOption | undefined {
  if (!validateChartRows(chart).renderable || !chart.allowedTypes.includes(type)) return undefined

  const chartPoints = points(chart)
  if (type === 'PIE') {
    return {
      animation: !reducedMotion,
      tooltip: { trigger: 'item' },
      legend: { bottom: 0 },
      series: [
        {
          type: 'pie',
          radius: ['36%', '68%'],
          data: chartPoints.map((point) => ({ name: point.label, value: point.value })),
          label: { formatter: '{b}: {d}%' },
        },
      ],
    }
  }

  return {
    animation: !reducedMotion,
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: chartPoints.map((point) => displayLabel(point.label)) },
    yAxis: { type: 'value', name: chart.unit ?? '' },
    series: [
      {
        type: type === 'LINE' ? 'line' : 'bar',
        name: chart.metricKey,
        data: chartPoints.map((point) => point.value),
        connectNulls: false,
        symbol: type === 'LINE' ? 'circle' : undefined,
        lineStyle: type === 'LINE' ? { type: 'solid' } : undefined,
      },
    ],
  }
}

export function summarizeChart(chart: ChartSeries, type: ChartType): ChartSummary {
  const chartPoints = points(chart)
  const numeric = chartPoints.filter(
    (point): point is { label: string; value: number } => point.value !== null,
  )
  const total = numeric.reduce((sum, point) => sum + point.value, 0)
  const unit = chart.unit ? ` ${chart.unit}` : ''
  const top = numeric.reduce<{ label: string; value: number } | undefined>(
    (current, point) => (!current || point.value > current.value ? point : current),
    undefined,
  )

  if (type === 'PIE') {
    const share = top && total !== 0 ? ((top.value / total) * 100).toFixed(1) : '0.0'
    return {
      total,
      sentence: top ? `合计 ${total}${unit}，${top.label} 占比 ${share}%。` : '没有可汇总的数据。',
    }
  }

  if (type === 'LINE' && numeric.length >= 2) {
    const first = numeric[0].value
    const last = numeric.at(-1)!.value
    if (first !== 0) {
      const change = ((last - first) / Math.abs(first)) * 100
      return { total, sentence: `合计 ${total}${unit}，末期较首期变化 ${change.toFixed(1)}%。` }
    }
  }

  return {
    total,
    sentence: top
      ? `合计 ${total}${unit}，${top.label} 为最高值 ${top.value}${unit}。`
      : '没有可汇总的数据。',
  }
}
