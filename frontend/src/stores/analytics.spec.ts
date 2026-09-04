import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/analytics', () => ({
  getChatBiOverview: vi.fn(),
  getChatBiCategories: vi.fn(),
  triggerChatBiRollup: vi.fn(),
}))

import { setLocaleProvider } from '@/api/credentials'
import { getChatBiCategories, getChatBiOverview } from '@/api/analytics'
import { useAnalyticsStore } from './analytics'
import { useLocaleStore } from './locale'

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

describe('analytics store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    setLocaleProvider(undefined)
  })

  it('没有管理员令牌时不发请求', async () => {
    const store = useAnalyticsStore()

    await expect(store.load()).rejects.toThrow(/未授权/)
    expect(getChatBiOverview).not.toHaveBeenCalled()
  })

  it('加载成功后同时填充总览与分类', async () => {
    vi.mocked(getChatBiOverview).mockResolvedValue(overview)
    vi.mocked(getChatBiCategories).mockResolvedValue([])
    const store = useAnalyticsStore()

    store.setAdminToken('demo-admin-token')
    await store.load()

    expect(store.overview?.answerTotal).toBe(10)
    expect(store.categories).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('请求失败时写入可读错误并复位 loading', async () => {
    vi.mocked(getChatBiOverview).mockRejectedValue(new Error('后端不可用'))
    const store = useAnalyticsStore()

    store.setAdminToken('demo-admin-token')
    await expect(store.load()).rejects.toThrow('后端不可用')

    expect(store.errorMessage).toContain('后端不可用')
    expect(store.loading).toBe(false)
  })
})

describe('语言切换：Chat BI 重新加载（Task 11 Step 6）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    setLocaleProvider(undefined)
  })

  it('已登录且已加载过总览时，切换语言会自动重新拉一次', async () => {
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    vi.mocked(getChatBiOverview).mockResolvedValue(overview)
    vi.mocked(getChatBiCategories).mockResolvedValue([])
    const store = useAnalyticsStore()
    store.setAdminToken('demo-admin-token')
    await store.load()
    vi.clearAllMocks()

    const enOverview = { ...overview, answerTotal: 99 }
    vi.mocked(getChatBiOverview).mockResolvedValue(enOverview)
    vi.mocked(getChatBiCategories).mockResolvedValue([])

    localeStore.setLocale('en-US')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(getChatBiOverview).toHaveBeenCalled()
    expect(store.overview?.answerTotal).toBe(99)
  })

  it('未登录时切换语言不发请求', async () => {
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    const store = useAnalyticsStore()

    localeStore.setLocale('en-US')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(getChatBiOverview).not.toHaveBeenCalled()
    expect(store.overview).toBeUndefined()
  })

  it('从未成功加载过总览时切换语言不发请求（避免抢在管理员输入令牌前发起注定失败的请求）', async () => {
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    const store = useAnalyticsStore()
    store.setAdminToken('demo-admin-token')

    localeStore.setLocale('en-US')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(getChatBiOverview).not.toHaveBeenCalled()
  })

  it('reloadForLocale 失败时静默吞掉，不产生未处理拒绝', async () => {
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    vi.mocked(getChatBiOverview).mockResolvedValue(overview)
    vi.mocked(getChatBiCategories).mockResolvedValue([])
    const store = useAnalyticsStore()
    store.setAdminToken('demo-admin-token')
    await store.load()

    vi.mocked(getChatBiOverview).mockRejectedValue(new Error('网络中断'))

    await expect(store.reloadForLocale()).resolves.toBeUndefined()
  })
})
