import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/analytics', () => ({
  getChatBiOverview: vi.fn(),
  getChatBiCategories: vi.fn(),
  triggerChatBiRollup: vi.fn(),
}))

import { getChatBiCategories, getChatBiOverview } from '@/api/analytics'
import { i18n } from '@/i18n'
import OpsDashboardView from './OpsDashboardView.vue'

function mountView() {
  return mount(OpsDashboardView, { global: { plugins: [createPinia(), i18n] } })
}

const overview = {
  startDate: '2026-08-17',
  endDate: '2026-08-23',
  answerTotal: 10,
  businessQuestionTotal: 9,
  feedbackTotal: 3,
  thinkingSampleCount: 10,
  metrics: {
    adoptionRate: 0.4,
    userAccuracyRate: null,
    systemAccuracyRate: 0.8,
    avgThinkingMs: 2500,
    hitRate: 0.9,
    failureRate: 0,
  },
  daily: [],
}

describe('OpsDashboardView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('没有管理员令牌时只展示令牌对话框且不请求指标', () => {
    const wrapper = mountView()

    expect(wrapper.find('#admin-token').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="north-star-card"]')).toHaveLength(0)
    expect(getChatBiOverview).not.toHaveBeenCalled()
  })

  it('验证令牌后渲染六项北极星指标', async () => {
    vi.mocked(getChatBiOverview).mockResolvedValue(overview)
    vi.mocked(getChatBiCategories).mockResolvedValue([])
    const wrapper = mountView()

    await wrapper.get('#admin-token').setValue('demo-admin-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.findAll('[data-testid="north-star-card"]')).toHaveLength(6)
  })

  it('加载失败时显示错误，且不展示可能陈旧的指标卡', async () => {
    vi.mocked(getChatBiOverview).mockRejectedValue(new Error('后端不可用'))
    const wrapper = mountView()

    await wrapper.get('#admin-token').setValue('demo-admin-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('后端不可用')
    expect(wrapper.findAll('[data-testid="north-star-card"]')).toHaveLength(0)
  })
})
