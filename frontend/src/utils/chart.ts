import type { SupportedLocale } from '@/i18n'
import type { ChartSeries } from '@/types/chat'

import { formatNumber } from './localizedFormat'
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
  /** 屏幕阅读器的图表口述摘要——`useEChart` 挂载的画布本身带 `aria-hidden`
   * （可访问入口是旁边的 `<details>` 数据表），这里额外把 ECharts 原生的
   * `aria` 描述也接上当前 locale，避免有人直接消费这份 option 时读到空/
   * 中文摘要。 */
  aria?: Record<string, unknown>
}

export interface ChartSummary {
  total: number
  sentence: string
}

export const SUPPORTED_TYPES: readonly ChartType[] = ['LINE', 'BAR', 'PIE']

const CHART_TYPE_LABELS_BY_LOCALE: Readonly<Record<SupportedLocale, Record<ChartType, string>>> = {
  'zh-CN': {
    LINE: '折线图',
    BAR: '柱状图',
    PIE: '饼图',
  },
  'en-US': {
    LINE: 'Line chart',
    BAR: 'Bar chart',
    PIE: 'Pie chart',
  },
}

/** 图表类型切换按钮的文案，按当前展示语言取值。 */
export function chartTypeLabel(type: ChartType, locale: SupportedLocale): string {
  return CHART_TYPE_LABELS_BY_LOCALE[locale][type]
}

interface ChartMessages {
  noData: string
  missingFields: string
  unsupportedType: string
  noSummary: string
}

const CHART_MESSAGES: Readonly<Record<SupportedLocale, ChartMessages>> = {
  'zh-CN': {
    noData: '本次回答没有可视化数据。',
    missingFields: '图表字段缺失，无法绘制。',
    unsupportedType: '图表类型暂不支持。',
    noSummary: '没有可汇总的数据。',
  },
  'en-US': {
    noData: 'This answer has no visualization data.',
    missingFields: 'Chart fields are missing, so the chart cannot be drawn.',
    unsupportedType: 'This chart type is not supported yet.',
    noSummary: 'There is no data to summarize.',
  },
}

/** `MetricChartPanel.vue` 在没有可渲染图表时复用同一份「没有可视化数据」文案。 */
export function chartNoDataMessage(locale: SupportedLocale): string {
  return CHART_MESSAGES[locale].noData
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

export function validateChartRows(
  chart: ChartSeries | undefined,
  locale: SupportedLocale,
): ChartValidation {
  const messages = CHART_MESSAGES[locale]
  if (!chart?.enabled || chart.data.length === 0) {
    return { renderable: false, reason: messages.noData }
  }
  if (!chart.dimensionKey || !chart.metricKey) {
    return { renderable: false, reason: messages.missingFields }
  }
  if (!chart.allowedTypes.some(isSupportedType)) {
    return { renderable: false, reason: messages.unsupportedType }
  }
  return { renderable: true }
}

export function toChartOption(
  chart: ChartSeries,
  type: ChartType,
  reducedMotion: boolean,
  locale: SupportedLocale,
): ChartOption | undefined {
  if (!validateChartRows(chart, locale).renderable || !chart.allowedTypes.includes(type))
    return undefined

  const chartPoints = points(chart)
  const aria = {
    enabled: true,
    label: { description: summarizeChart(chart, type, locale).sentence },
  }

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
      aria,
    }
  }

  return {
    animation: !reducedMotion,
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number | string) =>
        typeof value === 'number' ? formatNumber(value, locale) : value,
    },
    xAxis: { type: 'category', data: chartPoints.map((point) => displayLabel(point.label)) },
    yAxis: {
      type: 'value',
      name: chart.unit ?? '',
      axisLabel: { formatter: (value: number) => formatNumber(value, locale) },
    },
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
    aria,
  }
}

export function summarizeChart(
  chart: ChartSeries,
  type: ChartType,
  locale: SupportedLocale,
): ChartSummary {
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
  const noSummary = CHART_MESSAGES[locale].noSummary

  if (type === 'PIE') {
    const share = top && total !== 0 ? ((top.value / total) * 100).toFixed(1) : '0.0'
    return {
      total,
      sentence: top
        ? locale === 'en-US'
          ? `Total ${total}${unit}. ${top.label} accounts for ${share}%.`
          : `合计 ${total}${unit}，${top.label} 占比 ${share}%。`
        : noSummary,
    }
  }

  if (type === 'LINE' && numeric.length >= 2) {
    const first = numeric[0].value
    const last = numeric.at(-1)!.value
    if (first !== 0) {
      const change = ((last - first) / Math.abs(first)) * 100
      return {
        total,
        sentence:
          locale === 'en-US'
            ? `Total ${total}${unit}. Change from first to last period: ${change.toFixed(1)}%.`
            : `合计 ${total}${unit}，末期较首期变化 ${change.toFixed(1)}%。`,
      }
    }
  }

  return {
    total,
    sentence: top
      ? locale === 'en-US'
        ? `Total ${total}${unit}. Highest value: ${top.label} at ${top.value}${unit}.`
        : `合计 ${total}${unit}，${top.label} 为最高值 ${top.value}${unit}。`
      : noSummary,
  }
}
