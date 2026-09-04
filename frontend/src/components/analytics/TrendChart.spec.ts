import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

let capturedOption: { value?: Record<string, unknown> } | undefined

vi.mock('@/composables/useEChart', () => ({
  useEChart: (_container: unknown, option: { value?: Record<string, unknown> }) => {
    capturedOption = option
  },
}))

import TrendChart from './TrendChart.vue'

const DAILY = [
  {
    statDate: '2026-08-20',
    answerTotal: 8,
    metrics: {
      adoptionRate: 0.4,
      userAccuracyRate: null,
      systemAccuracyRate: 0.8,
      avgThinkingMs: 2100,
      hitRate: 0.9,
      failureRate: 0,
    },
  },
  {
    statDate: '2026-08-21',
    answerTotal: 12,
    metrics: {
      adoptionRate: null,
      userAccuracyRate: null,
      systemAccuracyRate: 0.75,
      avgThinkingMs: 1800,
      hitRate: null,
      failureRate: 0.1,
    },
  },
]

function mountChart() {
  return mount(TrendChart, { props: { daily: DAILY }, global: { plugins: [i18n] } })
}

describe('TrendChart', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('zh-CN')
  })

  it('将空比率保留为 null，供 ECharts 在趋势线上断开', () => {
    mountChart()

    const series = capturedOption?.value?.series as Array<Record<string, unknown>>
    expect(series[0]?.data).toEqual([40, null])
    expect(series[1]?.data).toEqual([90, null])
    expect(series[2]?.data).toEqual([8, 12])
  })

  it('日期原值保持不变，不按 locale 重新格式化', () => {
    mountChart()

    const xAxis = capturedOption?.value?.xAxis as Record<string, unknown>
    expect(xAxis.data).toEqual(['2026-08-20', '2026-08-21'])
  })

  it('中文 legend、轴名与 aria 摘要', () => {
    mountChart()

    const option = capturedOption?.value as Record<string, unknown>
    const legend = option.legend as { data: string[] }
    expect(legend.data).toEqual(['采纳率', '命中率', '问答量'])
    const yAxis = option.yAxis as Array<Record<string, unknown>>
    expect(yAxis[0]?.name).toBe('比率')
    expect(yAxis[1]?.name).toBe('问答量')
    const aria = option.aria as { label: { description: string } }
    expect(aria.label.description).toBe('展示统计窗口内采纳率、命中率与问答量的每日趋势。')
  })

  it('tooltip 的 valueFormatter 按 locale 格式化数值', () => {
    mountChart()

    const option = capturedOption?.value as Record<string, unknown>
    const tooltip = option.tooltip as { valueFormatter: (value: number | string) => unknown }
    expect(tooltip.valueFormatter(1234.5)).toBe('1,234.5')
    // 非数值（例如坐标轴的 name 占位）原样返回，不强行转换
    expect(tooltip.valueFormatter('n/a')).toBe('n/a')
  })

  /**
   * 画布标题只由 DOM 的 `<h2 id="trend-chart-title">` 承担（已随 locale
   * 正确切换）。这里显式断言 option 里没有 `title` 字段，防止 ECharts 原生
   * title 组件被重新加回来，导致同一句话在页面上渲染两次
   * （一次在 `<h2>`，一次画进画布本身）——这正是本组件与
   * `MetricChartPanel.vue`（只用 DOM `<figcaption>`）保持一致的地方。
   */
  it('不在 ECharts option 里设置原生 title，避免与 DOM 标题重复渲染', () => {
    const wrapper = mountChart()

    const option = capturedOption?.value as Record<string, unknown>
    expect(option.title).toBeUndefined()
    expect(wrapper.findAll('#trend-chart-title')).toHaveLength(1)
    expect(wrapper.get('#trend-chart-title').text()).toBe('采纳率、命中率与问答量')
  })
})

describe('TrendChart en-US 下 option 被重新构建为英文', () => {
  // 故意从 zh-CN 起步：每个测试自己在断言「重建前」的中文快照之后，
  // 再切到 en-US 断言「重建后」的英文快照，用来证明 option 是被整份替换
  // 而不是原地改字符串——不是复制粘贴遗留，是这组测试的设计意图。
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('zh-CN')
  })

  it('legend、轴名与 aria 摘要均为英文；技术数值不改写', () => {
    mountChart()
    const before = capturedOption?.value as Record<string, unknown>

    useLocaleStore().setLocale('en-US')
    const after = capturedOption?.value as Record<string, unknown>

    // 重建而非原地修改：切换前捕获的对象引用保持旧文案不变。
    expect(before).not.toBe(after)
    expect((before.legend as { data: string[] }).data).toEqual(['采纳率', '命中率', '问答量'])

    expect((after.legend as { data: string[] }).data).toEqual([
      'Adoption rate',
      'Hit rate',
      'Answers',
    ])
    const yAxis = after.yAxis as Array<Record<string, unknown>>
    expect(yAxis[0]?.name).toBe('Rate')
    expect(yAxis[1]?.name).toBe('Answers')
    const aria = after.aria as { label: { description: string } }
    expect(aria.label.description).toBe(
      'Shows the daily trend of adoption rate, hit rate, and answer volume within the selected window.',
    )
    // 画布内不设置 title，两个 locale 下都不应该出现该字段。
    expect(before.title).toBeUndefined()
    expect(after.title).toBeUndefined()

    // 数值和原始日期字符串不随 locale 改写
    const series = after.series as Array<Record<string, unknown>>
    expect(series[0]?.data).toEqual([40, null])
    const xAxis = after.xAxis as Record<string, unknown>
    expect(xAxis.data).toEqual(['2026-08-20', '2026-08-21'])
  })

  it('axis formatter 按新 locale 重新求值', () => {
    mountChart()
    useLocaleStore().setLocale('en-US')
    const option = capturedOption?.value as Record<string, unknown>
    const yAxis = option.yAxis as Array<Record<string, unknown>>
    const axisLabel = yAxis[0]?.axisLabel as { formatter: string }
    // 比率轴仍以百分号格式化，中英文一致，不因 locale 改写符号本身
    expect(axisLabel.formatter).toBe('{value}%')
  })

  it('tooltip 的 valueFormatter 按新 locale 重新求值', () => {
    mountChart()
    const before = capturedOption?.value as Record<string, unknown>
    const beforeFormatter = (before.tooltip as { valueFormatter: (v: number) => unknown })
      .valueFormatter

    useLocaleStore().setLocale('en-US')
    const after = capturedOption?.value as Record<string, unknown>
    const afterFormatter = (after.tooltip as { valueFormatter: (v: number) => unknown })
      .valueFormatter

    // zh-CN 和 en-US 的千分位分组习惯本身相同（都是逗号），这里重点验证
    // 的是 formatter 函数随 option 一起被重新构建，而不是复用旧闭包。
    expect(beforeFormatter).not.toBe(afterFormatter)
    expect(afterFormatter(1234.5)).toBe('1,234.5')
  })

  it('canvas 的 aria-label 随 locale 切换为英文', async () => {
    const wrapper = mountChart()
    useLocaleStore().setLocale('en-US')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.trend-chart__canvas').attributes('aria-label')).toBe(
      'Chat BI daily trend chart',
    )
  })

  it('DOM 标题随 locale 切换为英文，且仍然只渲染一次', async () => {
    const wrapper = mountChart()
    useLocaleStore().setLocale('en-US')
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('#trend-chart-title')).toHaveLength(1)
    expect(wrapper.get('#trend-chart-title').text()).toBe(
      'Adoption rate, hit rate, and answer volume',
    )
    const option = capturedOption?.value as Record<string, unknown>
    expect(option.title).toBeUndefined()
  })

  it('没有日趋势数据时空态提示为英文', async () => {
    useLocaleStore().setLocale('en-US')
    const wrapper = mount(TrendChart, { props: { daily: [] }, global: { plugins: [i18n] } })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('No daily trend data for the current window.')
  })
})
