import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { toChatAnswer } from '@/api/adapters/chat'
import { CHAT_FIXTURES } from '@/api/mock/fixtures.generated'
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

describe('MetricDefinitionPanel', () => {
  it('展示口径、来源、负责人与状态', () => {
    const wrapper = mount(MetricDefinitionPanel, { props: { answer: metricAnswer } })

    expect(wrapper.text()).toContain(metricAnswer.metric!.displayName)
    expect(wrapper.text()).toContain(metricAnswer.metric!.source)
    expect(wrapper.text()).toContain(metricAnswer.metric!.owner)
  })

  it('将后端 query_plan 明确标注为查询计划摘要', () => {
    const wrapper = mount(MetricDefinitionPanel, { props: { answer: metricAnswer } })

    expect(wrapper.text()).toContain('查询计划摘要')
    expect(wrapper.text()).toContain(metricAnswer.data!.queryPlan!)
  })

  it('RULE 模式没有指标时显示空状态而不是零值', () => {
    const wrapper = mount(MetricDefinitionPanel, { props: { answer: ruleAnswer } })

    expect(wrapper.find('[data-testid="metric-empty"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('undefined')
  })
})

describe('MetricChartPanel', () => {
  it('受控查询数据没有 visualization 时显示空状态，不伪造图表', () => {
    const wrapper = mount(MetricChartPanel, { props: { answer: disabledChartAnswer } })

    expect(wrapper.get('[data-testid="chart-empty"]').text()).toContain('本次回答没有可视化数据')
    expect(wrapper.find('[data-testid="chart-summary"]').exists()).toBe(false)
    expect(wrapper.find('canvas').exists()).toBe(false)
  })

  it('后端提供 visualization 时展示图表摘要', () => {
    const wrapper = mount(MetricChartPanel, { props: { answer: metricAnswer } })

    expect(wrapper.get('[data-testid="chart-summary"]').text()).toContain('128000')
    expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(false)
  })

  it('即使 canvas 未初始化也保留图表摘要和可键盘访问的数据表', () => {
    const wrapper = mount(MetricChartPanel, { props: { answer: chartAnswer } })

    expect(wrapper.get('[data-testid="chart-summary"]').text()).toContain('食品')
    expect(wrapper.get('details').text()).toContain('查看数据表')
    expect(wrapper.findAll('th[scope="col"]')).toHaveLength(2)
    expect(wrapper.find('[data-testid="chart-type-switcher"]').exists()).toBe(true)
  })
})

describe('RecommendationPanel', () => {
  it('展示建议三要素并可直接发送猜你想问', async () => {
    const wrapper = mount(RecommendationPanel, { props: { answer: metricAnswer } })

    const first = metricAnswer.recommendations[0]
    expect(wrapper.text()).toContain(first.title)
    expect(wrapper.text()).toContain(first.evidence)
    expect(wrapper.text()).toContain(first.action)

    await wrapper.get('[data-testid="suggested-question"]').trigger('click')
    expect(wrapper.emitted('ask')?.[0]?.[0]).toBe(metricAnswer.suggestions.current[0])
  })

  it('没有回答时显示空状态', () => {
    const wrapper = mount(RecommendationPanel, { props: { answer: undefined } })

    expect(wrapper.find('[data-testid="recommendation-empty"]').exists()).toBe(true)
  })

  it('换一换只在响应给出的备选问题中本地循环', async () => {
    const wrapper = mount(RecommendationPanel, { props: { answer: metricAnswer } })
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
    const wrapper = mount(RecommendationPanel, { props: { answer: answerWithoutAlternates } })

    expect(wrapper.find('[data-testid="rotate-suggestions"]').exists()).toBe(false)
  })
})
