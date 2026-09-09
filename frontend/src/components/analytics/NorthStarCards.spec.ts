import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

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

function mountCards(metrics: typeof FULL | typeof EMPTY) {
  return mount(NorthStarCards, { props: { metrics }, global: { plugins: [i18n] } })
}

describe('NorthStarCards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('zh-CN')
  })

  it('为六项北极星指标各渲染一张卡', () => {
    const wrapper = mountCards(FULL)

    expect(wrapper.findAll('[data-testid="north-star-card"]')).toHaveLength(6)
  })

  it('将比率渲染为百分比，将思考时长渲染为秒', () => {
    const wrapper = mountCards(FULL)

    expect(wrapper.text()).toContain('40.0%')
    expect(wrapper.text()).toContain('2.5 秒')
  })

  it('样本不足时显示文案而不伪造为零比率', () => {
    const wrapper = mountCards(EMPTY)

    expect(wrapper.text()).toContain('样本不足')
    expect(wrapper.text()).not.toContain('0.0%')
  })

  it('分开标示用户侧和系统侧准确率以保留口径', () => {
    const wrapper = mountCards(FULL)

    expect(wrapper.text()).toContain('用户侧准确率')
    expect(wrapper.text()).toContain('系统侧准确率')
  })
})

describe('NorthStarCards en-US 下文案为英文，数值不改写', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('en-US')
  })

  it('标签、提示语和单位均为英文，百分比与数值原样保留', () => {
    const wrapper = mountCards(FULL)

    expect(wrapper.text()).toContain('Adoption rate')
    expect(wrapper.text()).toContain('Share of answers merchants clicked to adopt')
    expect(wrapper.text()).toContain('User-side accuracy')
    expect(wrapper.text()).toContain('System-side accuracy')
    expect(wrapper.text()).toContain('Reviewer first-pass rate')
    expect(wrapper.text()).toContain('Average thinking time')
    expect(wrapper.text()).toContain('Question hit rate')
    expect(wrapper.text()).toContain('Answer failure rate')
    // 数值本身不随 locale 改写
    expect(wrapper.text()).toContain('40.0%')
    expect(wrapper.text()).toContain('2.5 s')
  })

  it('样本不足时显示英文文案而不是中文或伪造的零比率', () => {
    const wrapper = mountCards(EMPTY)

    expect(wrapper.text()).toContain('Insufficient sample')
    expect(wrapper.text()).not.toContain('样本不足')
    expect(wrapper.text()).not.toContain('0.0%')
  })
})
