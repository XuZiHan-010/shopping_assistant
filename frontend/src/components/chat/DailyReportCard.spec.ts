import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DailyReportCard from './DailyReportCard.vue'

const report = {
  answerId: '00000000-0000-0000-0000-000000000001',
  reportDate: '2026-08-20',
  metrics: [
    { code: 'gmv', displayName: '成交金额', unit: '元', value: '12680.00' },
    { code: 'order_count', displayName: '订单量', unit: '单', value: 92 },
  ],
  suggestions: ['先处理退款问题。', '关注订单转化。'],
  degraded: false,
}

describe('DailyReportCard', () => {
  it('展示日期、核心指标和两条建议', () => {
    const wrapper = mount(DailyReportCard, { props: { report } })

    expect(wrapper.text()).toContain('2026-08-20')
    expect(wrapper.text()).toContain('成交金额')
    expect(wrapper.findAll('.daily-report__suggestions li')).toHaveLength(2)
  })

  it('点击采纳时发出事件，已采纳后禁用按钮', async () => {
    const wrapper = mount(DailyReportCard, { props: { report } })

    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('adopt')).toHaveLength(1)

    await wrapper.setProps({ adopted: true })
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  })
})
