import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CategoryTable from './CategoryTable.vue'

describe('CategoryTable', () => {
  it('展示分类名称、问答量和所有六项指标', () => {
    const wrapper = mount(CategoryTable, {
      props: {
        rows: [
          {
            category: 'TRADE',
            displayName: '交易分析',
            answerTotal: 12,
            metrics: {
              adoptionRate: 0.5,
              userAccuracyRate: 0.75,
              systemAccuracyRate: 0.8,
              avgThinkingMs: 2000,
              hitRate: 0.9,
              failureRate: 0.1,
            },
          },
        ],
      },
    })

    expect(wrapper.text()).toContain('交易分析')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.findAll('thead th')).toHaveLength(8)
    expect(wrapper.text()).toContain('50.0%')
    expect(wrapper.text()).toContain('2.0 秒')
  })

  it('将空指标显示为样本不足而不是零', () => {
    const wrapper = mount(CategoryTable, {
      props: {
        rows: [
          {
            category: 'UNKNOWN',
            displayName: '未分类',
            answerTotal: 1,
            metrics: {
              adoptionRate: null,
              userAccuracyRate: null,
              systemAccuracyRate: null,
              avgThinkingMs: null,
              hitRate: null,
              failureRate: null,
            },
          },
        ],
      },
    })

    expect(wrapper.text()).toContain('样本不足')
    expect(wrapper.text()).not.toContain('0.0%')
  })
})
