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
import { useLocaleStore } from '@/stores/locale'

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
    useLocaleStore().setLocale('zh-CN')
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

describe('OpsDashboardView en-US 下确定性文案为英文', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('en-US')
    vi.clearAllMocks()
  })

  it('令牌对话框标题、窗口选择、刷新按钮均为英文，并插入统一语言切换器', () => {
    const wrapper = mountView()

    expect(wrapper.get('h1').text()).toBe('Chat BI operations dashboard')
    // 语言切换器在授权前（令牌对话框阶段）就要可用——直接落地在 /ops-dashboard
    // 的用户（例如收藏的管理链接）在输入令牌之前也应该能切换语言，不必先
    // 猜对存量语言才能看懂这个对话框（Finding 4：之前只在 v-else 分支里
    // 渲染，未授权页面完全够不到它）。
    expect(wrapper.find('[data-testid="language-switcher"]').exists()).toBe(true)
  })

  it('验证令牌后顶栏、窗口选择、刷新按钮、指标卡与分类表均为英文', async () => {
    vi.mocked(getChatBiOverview).mockResolvedValue(overview)
    vi.mocked(getChatBiCategories).mockResolvedValue([
      {
        category: 'TRADE',
        displayName: 'Trade analysis',
        answerTotal: 5,
        metrics: {
          adoptionRate: 0.5,
          userAccuracyRate: null,
          systemAccuracyRate: 0.6,
          avgThinkingMs: 1500,
          hitRate: 0.7,
          failureRate: 0.05,
        },
      },
    ])
    const wrapper = mountView()

    await wrapper.get('#admin-token').setValue('demo-admin-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('h1').text()).toBe('Chat BI operations dashboard')
    expect(wrapper.find('[data-testid="language-switcher"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Sign out')
    expect(wrapper.text()).toContain('Last 7 days')
    expect(wrapper.text()).toContain('Last 30 days')
    expect(wrapper.text()).toContain('Last 90 days')
    expect(wrapper.text()).toContain('Refresh rollup')
    expect(wrapper.text()).toContain('Adoption rate')
    expect(wrapper.text()).toContain('Trade analysis')
    expect(wrapper.text()).toContain('Category drill-down')
    // metric_code / 数值均不改写
    expect(wrapper.text()).toContain('40.0%')
  })

  it('加载失败时显示英文错误提示', async () => {
    vi.mocked(getChatBiOverview).mockRejectedValue(new Error('Backend unavailable'))
    const wrapper = mountView()

    await wrapper.get('#admin-token').setValue('demo-admin-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Backend unavailable')
  })

  it('加载态提示为英文', async () => {
    vi.mocked(getChatBiOverview).mockImplementation(() => new Promise(() => undefined))
    const wrapper = mountView()

    await wrapper.get('#admin-token').setValue('demo-admin-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Loading Chat BI data…')
  })
})
