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

const metricAnswer = toChatAnswer(CHAT_FIXTURES.metricGmv as components['schemas']['ChatResponse'])
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

describe('MetricChartPanel', () => {
  it('受控查询数据没有 visualization 时显示空状态，不伪造图表', () => {
    const wrapper = mountWithI18n(MetricChartPanel, { chart: disabledChartAnswer.chart })

    expect(wrapper.get('[data-testid="chart-empty"]').text()).toContain('本次回答没有可视化数据')
    expect(wrapper.find('[data-testid="chart-summary"]').exists()).toBe(false)
    expect(wrapper.find('canvas').exists()).toBe(false)
  })

  it('后端提供 visualization 时展示图表摘要', () => {
    const wrapper = mountWithI18n(MetricChartPanel, { chart: metricAnswer.chart })
    const summary = wrapper.get('[data-testid="chart-summary"]').text()

    expect(summary).toContain('合计 128,000.5 元')
    expect(summary).toContain('为最高值 128,000.5 元')
    expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(false)
  })

  it('即使 canvas 未初始化也保留图表摘要和可键盘访问的数据表', () => {
    const wrapper = mountWithI18n(MetricChartPanel, { chart: chartAnswer.chart })

    expect(wrapper.get('[data-testid="chart-summary"]').text()).toContain('食品')
    expect(wrapper.get('details').text()).toContain('查看数据表')
    expect(wrapper.findAll('th[scope="col"]')).toHaveLength(2)
    expect(wrapper.find('[data-testid="chart-type-switcher"]').exists()).toBe(true)
  })

  it('en-US 下空态、类型切换按钮和"查看数据表"均为英文；option.aria 描述也读取当前 locale', () => {
    useLocaleStore().setLocale('en-US')
    const empty = mountWithI18n(MetricChartPanel, { chart: disabledChartAnswer.chart })
    expect(empty.get('[data-testid="chart-empty"]').text()).toContain(
      'This answer has no visualization data',
    )

    const withChart = mountWithI18n(MetricChartPanel, { chart: chartAnswer.chart })
    expect(withChart.get('details').text()).toContain('View data table')
    expect(withChart.text()).toContain('Bar chart')
    expect(withChart.text()).toContain('Pie chart')
    // 图表标题（`chart.title`）是后端已本地化字段，原样透传，不由前端重译。
    expect(withChart.text()).toContain('类目成交 GMV')
  })

  it('类型切换只提供后端声明且前端支持的图表类型，点击后摘要按新类型重算（PRD §12.3）', async () => {
    const wrapper = mountWithI18n(MetricChartPanel, {
      chart: { ...chartAnswer.chart, allowedTypes: ['BAR', 'PIE', 'RADAR'] },
    })
    const buttons = wrapper.get('[data-testid="chart-type-switcher"]').findAll('button')

    // 后端声明了三种，前端不认识 RADAR：不提供它，也不自行加上后端没声明的折线图。
    expect(buttons.map((button) => button.text())).toEqual(['柱状图', '饼图'])
    // 默认取后端声明的第一种（柱状图）：摘要讲最高值，不讲占比。
    expect(wrapper.get('[data-testid="chart-summary"]').text()).not.toContain('占比')

    await buttons[1]!.trigger('click')

    // 数据点没变（仍是查询结果里的两行），只是换了呈现与摘要口径。
    expect(wrapper.get('[data-testid="chart-summary"]').text()).toContain('食品 占比 60.0%')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)

    await buttons[0]!.trigger('click')
    expect(wrapper.get('[data-testid="chart-summary"]').text()).not.toContain('占比')
  })

  it('后端只声明一种类型时不显示类型切换（时间趋势固定为折线图）', () => {
    const wrapper = mountWithI18n(MetricChartPanel, {
      chart: { ...chartAnswer.chart, type: 'LINE', allowedTypes: ['LINE'] },
    })

    expect(wrapper.find('[data-testid="chart-type-switcher"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="chart-summary"]').text().length).toBeGreaterThan(0)
  })
})

