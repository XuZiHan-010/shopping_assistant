import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import CategoryTable from './CategoryTable.vue'

function mountTable(rows: Array<Record<string, unknown>>) {
  return mount(CategoryTable, { props: { rows }, global: { plugins: [i18n] } })
}

describe('CategoryTable', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('zh-CN')
  })

  it('展示分类名称、问答量和所有六项指标', () => {
    const wrapper = mountTable([
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
    ])

    expect(wrapper.text()).toContain('交易分析')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.findAll('thead th')).toHaveLength(8)
    expect(wrapper.text()).toContain('50.0%')
    expect(wrapper.text()).toContain('2.0 秒')
  })

  it('将空指标显示为样本不足而不是零', () => {
    const wrapper = mountTable([
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
    ])

    expect(wrapper.text()).toContain('样本不足')
    expect(wrapper.text()).not.toContain('0.0%')
  })
})

describe('CategoryTable en-US 下表头和空态为英文，技术 key 与数值不改写', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('en-US')
  })

  it('表头、eyebrow 和标题均为英文，displayName 与 category 原样透传', () => {
    // displayName 视为后端已按当前 locale 本地化的人类可读副本
    // （见 routes/analytics.py 的 _display_name()）；这里直接用英文
    // fixture 模拟后端返回，前端不得对它再做二次翻译。
    const wrapper = mountTable([
      {
        category: 'TRADE',
        displayName: 'Trade analysis',
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
    ])

    const headers = wrapper.findAll('thead th').map((th) => th.text())
    expect(headers).toEqual([
      'Question category',
      'Answers',
      'Adoption rate',
      'User-side accuracy',
      'System-side accuracy',
      'Avg. thinking time',
      'Hit rate',
      'Failure rate',
    ])
    expect(wrapper.text()).toContain('Trade analysis')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.text()).toContain('50.0%')
    expect(wrapper.text()).toContain('2.0 s')
    expect(wrapper.text()).not.toContain('问题分类')
  })

  it('样本不足时显示英文文案，不伪造为零比率', () => {
    const wrapper = mountTable([
      {
        category: 'UNKNOWN',
        displayName: 'Uncategorized',
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
    ])

    expect(wrapper.text()).toContain('Insufficient sample')
    expect(wrapper.text()).not.toContain('0.0%')
  })

  it('空态提示为英文', () => {
    const wrapper = mountTable([])

    expect(wrapper.text()).toContain('No category data to drill into for the current window.')
  })
})
