import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { toChatAnswer } from '@/api/adapters/chat'
import { CHAT_FIXTURES } from '@/api/mock/fixtures.generated'
import type { components } from '@/api/generated'

import MetricChartPanel from './MetricChartPanel.vue'
import MetricDefinitionPanel from './MetricDefinitionPanel.vue'
import RecommendationPanel from './RecommendationPanel.vue'

const metricAnswer = toChatAnswer(CHAT_FIXTURES.metricGmv as components['schemas']['ChatResponse'])
const ruleAnswer = toChatAnswer(CHAT_FIXTURES.rulePlatform as components['schemas']['ChatResponse'])

describe('MetricDefinitionPanel', () => {
  it('展示口径、来源、负责人与状态', () => {
    const wrapper = mount(MetricDefinitionPanel, { props: { answer: metricAnswer } })

    expect(wrapper.text()).toContain(metricAnswer.metric!.displayName)
    expect(wrapper.text()).toContain(metricAnswer.metric!.source)
    expect(wrapper.text()).toContain(metricAnswer.metric!.owner)
  })

  it('RULE 模式没有指标时显示空状态而不是零值', () => {
    const wrapper = mount(MetricDefinitionPanel, { props: { answer: ruleAnswer } })

    expect(wrapper.find('[data-testid="metric-empty"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('undefined')
  })
})

describe('MetricChartPanel', () => {
  it('B3 尚未查询数据时不伪造图表', () => {
    const wrapper = mount(MetricChartPanel, { props: { answer: metricAnswer } })

    expect(wrapper.get('[data-testid="chart-empty"]').text()).toContain('暂无图表')
    expect(wrapper.find('canvas').exists()).toBe(false)
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
})
