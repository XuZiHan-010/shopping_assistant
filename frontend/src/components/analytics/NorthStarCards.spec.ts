import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import NorthStarCards from './NorthStarCards.vue'

const FULL = {
  adoptionRate: 0.4,
  userAccuracyRate: 0.75,
  systemAccuracyRate: 0.8,
  avgThinkingMs: 2500,
  hitRate: 0.9,
  failureRate: 0.05,
}

const EMPTY = {
  adoptionRate: null,
  userAccuracyRate: null,
  systemAccuracyRate: null,
  avgThinkingMs: null,
  hitRate: null,
  failureRate: null,
}

describe('NorthStarCards', () => {
  it('为六项北极星指标各渲染一张卡', () => {
    const wrapper = mount(NorthStarCards, { props: { metrics: FULL } })

    expect(wrapper.findAll('[data-testid="north-star-card"]')).toHaveLength(6)
  })

  it('将比率渲染为百分比，将思考时长渲染为秒', () => {
    const wrapper = mount(NorthStarCards, { props: { metrics: FULL } })

    expect(wrapper.text()).toContain('40.0%')
    expect(wrapper.text()).toContain('2.5 秒')
  })

  it('样本不足时显示文案而不伪造为零比率', () => {
    const wrapper = mount(NorthStarCards, { props: { metrics: EMPTY } })

    expect(wrapper.text()).toContain('样本不足')
    expect(wrapper.text()).not.toContain('0.0%')
  })

  it('分开标示用户侧和系统侧准确率以保留口径', () => {
    const wrapper = mount(NorthStarCards, { props: { metrics: FULL } })

    expect(wrapper.text()).toContain('用户侧准确率')
    expect(wrapper.text()).toContain('系统侧准确率')
  })
})
