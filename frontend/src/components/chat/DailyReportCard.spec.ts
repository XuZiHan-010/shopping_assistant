import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

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

function mountCard(props: Record<string, unknown>) {
  return mount(DailyReportCard, { props, global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('DailyReportCard', () => {
  it('展示日期、核心指标和两条建议', () => {
    const wrapper = mountCard({ report })

    // 日期按当前展示语言本地化渲染（zh-CN 用 Intl 'medium' 样式），机器可读的
    // ISO 原值仍保留在 <time datetime> 上。
    expect(wrapper.get('time').attributes('datetime')).toBe('2026-08-20')
    expect(wrapper.text()).toContain('2026年8月20日')
    expect(wrapper.text()).toContain('成交金额')
    expect(wrapper.findAll('.daily-report__suggestions li')).toHaveLength(2)
  })

  it('点击采纳时发出事件，已采纳后禁用按钮', async () => {
    const wrapper = mountCard({ report })

    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('adopt')).toHaveLength(1)

    await wrapper.setProps({ adopted: true })
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  })

  it('en-US 下标题、日期和采纳按钮均为英文，指标展示名/单位保持后端已本地化的原样', () => {
    useLocaleStore().setLocale('en-US')
    const wrapper = mountCard({ report })

    expect(wrapper.text()).toContain('Daily business report')
    expect(wrapper.get('time').attributes('datetime')).toBe('2026-08-20')
    expect(wrapper.text()).toContain('Aug 20, 2026')
    expect(wrapper.get('button').text()).toContain('Adopt this report')
    // 指标展示名/单位是后端按 Accept-Language 提供的字段，前端不重译；这里
    // 直接复用测试夹具里的中文值，验证组件原样透传而不是自己再翻译一遍。
    expect(wrapper.text()).toContain('成交金额')
  })
})
