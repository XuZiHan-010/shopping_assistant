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

/** 手动控制 settle 时机的 Promise，用来构造"谁先谁后返回"的确定性竞态。 */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
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

describe('语言切换：epoch 竞态防护（Task 11 Step 6 补齐到 analytics.ts）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    setLocaleProvider(undefined)
  })

  it('中文响应晚到、英语响应先到：真实乱序下，晚到的中文响应不会覆盖已经写入的英语数据', async () => {
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    const store = useAnalyticsStore()
    store.setAdminToken('demo-admin-token')

    // 先成功加载一次，让 reloadForLocale 的"从未加载过就跳过"门槛通过。
    vi.mocked(getChatBiOverview).mockResolvedValueOnce(overview)
    vi.mocked(getChatBiCategories).mockResolvedValue([])
    await store.load()

    const zh = deferred<typeof overview>()
    const en = deferred<typeof overview>()
    // 按"第几次调用"分发响应，不按调用那一刻读到的 locale 分发——与
    // chat.spec.ts 的竞态测试同一个理由：真正关心的是"先发出的请求" vs
    // "语言切换后发出的请求"谁的响应先到、Store 是否按 epoch 正确取舍。
    let callCount = 0
    vi.mocked(getChatBiOverview).mockImplementation(async () => {
      callCount += 1
      return callCount === 1 ? zh.promise : en.promise
    })

    // 模拟"手动点了一次刷新，中文请求还没回来，用户就切到了英语"：先手动
    // 发起一次中文 load()（不经过 reloadForLocale，代表任意一次仍在途的
    // 刷新），再切语言触发 reloadForLocale（epoch += 1，发出新的英语请求）。
    const staleZhLoad = store.load()
    localeStore.setLocale('en-US')

    // 英语先回来。
    en.resolve({ ...overview, answerTotal: 999 })
    await vi.waitFor(() => expect(store.overview?.answerTotal).toBe(999))

    // 中文后回来——必须被丢弃，不能覆盖已经写入的英语数据。
    zh.resolve({ ...overview, answerTotal: 1 })
    await staleZhLoad
    // 给一次事件循环，确认"迟到的中文响应"确实被处理过（而不是还没跑到那一行）。
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.overview?.answerTotal).toBe(999)
  })
})
