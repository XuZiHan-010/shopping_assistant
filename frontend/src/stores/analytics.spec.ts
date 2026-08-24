import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/analytics', () => ({
  getChatBiOverview: vi.fn(),
  getChatBiCategories: vi.fn(),
  triggerChatBiRollup: vi.fn(),
}))

import { getChatBiCategories, getChatBiOverview } from '@/api/analytics'
import { useAnalyticsStore } from './analytics'

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
