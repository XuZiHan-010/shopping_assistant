import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { toChatAnswer } from '@/api/adapters/chat'
import { CHAT_FIXTURES } from '@/api/mock/fixtures.generated'
import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'
import type { components } from '@/api/generated'
import type { ChatAnswer } from '@/types/chat'

import MetricChartPanel from './MetricChartPanel.vue'
import MetricDefinitionPanel from './MetricDefinitionPanel.vue'
import RecommendationPanel from './RecommendationPanel.vue'

const metricAnswer = toChatAnswer(CHAT_FIXTURES.metricGmv as components['schemas']['ChatResponse'])
const ruleAnswer = toChatAnswer(CHAT_FIXTURES.rulePlatform as components['schemas']['ChatResponse'])
const disabledChartAnswer: ChatAnswer = {
  ...metricAnswer,
  chart: { enabled: false, allowedTypes: [], data: [] },
}
const chartAnswer: ChatAnswer = {
  ...metricAnswer,
  chart: {
    enabled: true,
    type: 'BAR',
    allowedTypes: ['BAR', 'PIE'],
    title: '类目成交 GMV',
    dimensionKey: 'category',
    metricKey: 'gmv',
    unit: '元',
    data: [
      { category: '食品', gmv: '60' },
      { category: '家居', gmv: '40' },
    ],
  },
}

function mountWithI18n<T>(component: T, props: Record<string, unknown>) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return mount(component as any, { props, global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('MetricDefinitionPanel', () => {
  it('展示口径、来源、负责人与状态', () => {
    const wrapper = mountWithI18n(MetricDefinitionPanel, { answer: metricAnswer })

    expect(wrapper.text()).toContain(metricAnswer.metric!.displayName)
    expect(wrapper.text()).toContain('正式指标目录')
    expect(wrapper.text()).toContain(metricAnswer.metric!.owner)
  })

  it('将后端 query_plan 明确标注为查询计划摘要', () => {
    const wrapper = mountWithI18n(MetricDefinitionPanel, { answer: metricAnswer })

    expect(wrapper.text()).toContain('查询计划摘要')
    expect(wrapper.text()).toContain(metricAnswer.data!.queryPlan!)
  })

  it('仅为通过 Adapter 校验的报表链接渲染安全新窗口链接', () => {
    const safeAnswer: ChatAnswer = {
      ...metricAnswer,
      metric: { ...metricAnswer.metric!, reportUrl: 'https://reports.example.com/gmv' },
    }
    const wrapper = mountWithI18n(MetricDefinitionPanel, { answer: safeAnswer })

    expect(wrapper.get('[data-testid="metric-report-link"]').attributes('href')).toBe(
      'https://reports.example.com/gmv',
    )
    expect(wrapper.get('[data-testid="metric-report-link"]').attributes('rel')).toBe(
      'noopener noreferrer',
    )
  })

  it('RULE 模式没有指标时显示空状态而不是零值', () => {
    const wrapper = mountWithI18n(MetricDefinitionPanel, { answer: ruleAnswer })

    expect(wrapper.find('[data-testid="metric-empty"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('undefined')
  })

  it('en-US 下字段标签、来源和状态文案均为英文，指标展示名/负责人保持后端已本地化的原样', () => {
    useLocaleStore().setLocale('en-US')
    const wrapper = mountWithI18n(MetricDefinitionPanel, { answer: metricAnswer })

    expect(wrapper.text()).toContain('Metric definition')
    expect(wrapper.text()).toContain('Business definition')
    expect(wrapper.text()).toContain('SQL definition')
    expect(wrapper.text()).toContain('Official metric catalog')
    expect(wrapper.text()).toContain('Query plan summary')
    // 展示名/负责人是后端按 Accept-Language 提供的字段，前端不重译。
    expect(wrapper.text()).toContain(metricAnswer.metric!.displayName)
  })
})

describe('MetricChartPanel', () => {
  it('受控查询数据没有 visualization 时显示空状态，不伪造图表', () => {
    const wrapper = mountWithI18n(MetricChartPanel, { answer: disabledChartAnswer })

    expect(wrapper.get('[data-testid="chart-empty"]').text()).toContain('本次回答没有可视化数据')
    expect(wrapper.find('[data-testid="chart-summary"]').exists()).toBe(false)
    expect(wrapper.find('canvas').exists()).toBe(false)
  })

  it('后端提供 visualization 时展示图表摘要', () => {
    const wrapper = mountWithI18n(MetricChartPanel, { answer: metricAnswer })
    const summary = wrapper.get('[data-testid="chart-summary"]').text()

    expect(summary).toContain('合计 128,000.5 元')
    expect(summary).toContain('为最高值 128,000.5 元')
    expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(false)
  })

  it('即使 canvas 未初始化也保留图表摘要和可键盘访问的数据表', () => {
    const wrapper = mountWithI18n(MetricChartPanel, { answer: chartAnswer })

    expect(wrapper.get('[data-testid="chart-summary"]').text()).toContain('食品')
    expect(wrapper.get('details').text()).toContain('查看数据表')
    expect(wrapper.findAll('th[scope="col"]')).toHaveLength(2)
    expect(wrapper.find('[data-testid="chart-type-switcher"]').exists()).toBe(true)
  })

  it('en-US 下空态、类型切换按钮和"查看数据表"均为英文；option.aria 描述也读取当前 locale', () => {
    useLocaleStore().setLocale('en-US')
    const empty = mountWithI18n(MetricChartPanel, { answer: disabledChartAnswer })
    expect(empty.get('[data-testid="chart-empty"]').text()).toContain(
      'This answer has no visualization data',
    )

    const withChart = mountWithI18n(MetricChartPanel, { answer: chartAnswer })
    expect(withChart.get('details').text()).toContain('View data table')
    expect(withChart.text()).toContain('Bar chart')
    expect(withChart.text()).toContain('Pie chart')
    // 图表标题（`chart.title`）是后端已本地化字段，原样透传，不由前端重译。
    expect(withChart.text()).toContain('类目成交 GMV')
  })
})

describe('RecommendationPanel', () => {
  it('展示建议三要素并可直接发送猜你想问', async () => {
    const wrapper = mountWithI18n(RecommendationPanel, { answer: metricAnswer })

    const first = metricAnswer.recommendations[0]
    expect(wrapper.text()).toContain(first.title)
    expect(wrapper.text()).toContain(first.evidence)
    expect(wrapper.text()).toContain(first.action)

    await wrapper.get('[data-testid="suggested-question"]').trigger('click')
    expect(wrapper.emitted('ask')?.[0]?.[0]).toBe(metricAnswer.suggestions.current[0])
  })

  it('没有回答时显示空状态', () => {
    const wrapper = mountWithI18n(RecommendationPanel, { answer: undefined })

    expect(wrapper.find('[data-testid="recommendation-empty"]').exists()).toBe(true)
  })

  it('换一换只在响应给出的备选问题中本地循环', async () => {
    const wrapper = mountWithI18n(RecommendationPanel, { answer: metricAnswer })
    const firstSet = wrapper
      .findAll('[data-testid="suggested-question"]')
      .map((item) => item.text())

    await wrapper.get('[data-testid="rotate-suggestions"]').trigger('click')
    const alternateSet = wrapper
      .findAll('[data-testid="suggested-question"]')
      .map((item) => item.text())

    expect(alternateSet).toEqual(metricAnswer.suggestions.alternates[0])
    expect(alternateSet).not.toEqual(firstSet)

    await wrapper.get('[data-testid="rotate-suggestions"]').trigger('click')
    expect(
      wrapper.findAll('[data-testid="suggested-question"]').map((item) => item.text()),
    ).toEqual(firstSet)
  })

  it('没有备选问题时不显示换一换按钮', () => {
    const answerWithoutAlternates: ChatAnswer = {
      ...metricAnswer,
      suggestions: { current: metricAnswer.suggestions.current, alternates: [] },
    }
    const wrapper = mountWithI18n(RecommendationPanel, { answer: answerWithoutAlternates })

    expect(wrapper.find('[data-testid="rotate-suggestions"]').exists()).toBe(false)
  })

  it('en-US 下标题、前缀和空态文案均为英文，建议标题/依据/行动保持后端已本地化的原样', () => {
    useLocaleStore().setLocale('en-US')
    const wrapper = mountWithI18n(RecommendationPanel, { answer: metricAnswer })

    expect(wrapper.text()).toContain('Action recommendations')
    expect(wrapper.text()).toContain('Evidence:')
    expect(wrapper.text()).toContain('Recommendation:')
    expect(wrapper.text()).toContain('You might also ask')
    expect(wrapper.get('[data-testid="rotate-suggestions"]').text()).toBe('Shuffle')

    const empty = mountWithI18n(RecommendationPanel, { answer: undefined })
    expect(empty.text()).toContain('No recommendations yet')
  })
})
