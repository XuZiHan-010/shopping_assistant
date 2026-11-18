import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setCredentialProvider } from '@/api/credentials'
import { AppError } from '@/api/errors'
import { setChatTransport } from '@/api/transport'
import { i18n } from '@/i18n'
import { useKnowledgeStore } from '@/stores/knowledge'
import type { ChatBiOverview, OpsStatus } from '@/types/opsStatus'

import OpsStatusView from './OpsStatusView.vue'

const DATABASE_USAGE = {
  collectedAt: '2026-11-19T00:00:00Z',
  databaseSizeBytes: 256 * 1024 ** 2,
  storageLimitBytes: null,
  storageUsedRatio: null,
  maxConnections: 100,
  connectionsTotal: 7,
  connectionsActive: 2,
  topTables: [{ tableName: 'memory_outbox', totalBytes: 2048, estimatedRows: null }],
  memoryOutbox: { pending: 3, processing: 4, failed: 0, done: 5, oldestPendingAgeSeconds: 1800 },
}

const adapter = vi.hoisted(() => ({
  fetchOpsStatus: vi.fn(),
  fetchChatBiOverview: vi.fn(),
}))
vi.mock('@/api/adapters/adminOps', () => adapter)

const STATUS: OpsStatus = {
  tokensUsedToday: 1200,
  tokensRemainingToday: 3800,
  callsToday: 4,
  rateLimitHits: 2,
  degradedCount: 1,
  errorCodeCounts: { RATE_LIMITED: 2 },
  budgetLevels: [
    {
      level: 'GLOBAL',
      scope: 'GLOBAL',
      budgetTokens: 5000,
      usedTokens: 1200,
      remainingTokens: 3800,
    },
    {
      level: 'ROLE',
      scope: 'ROLE:CUSTOMER',
      budgetTokens: 2000,
      usedTokens: 200,
      remainingTokens: 1800,
    },
    {
      level: 'SHOP',
      scope: 'SHOP:MERCHANT:1a2b3c4d',
      budgetTokens: 1000,
      usedTokens: 1000,
      remainingTokens: 0,
    },
  ],
  costToday: [{ currency: 'USD', amount: '0.75000000' }],
  unpricedCallsToday: 1,
  cacheHitTokensToday: 400,
  cacheHitRateToday: 0.2,
  toolCallsTotal: 10,
  toolErrorsTotal: 1,
  toolErrorRate: 0.1,
  routeP95: [{ route: '/api/v2/merchant/chat', p95Ms: 1800 }],
  demoDeploymentMode: true,
  turnsToday: 2,
  avgTokensPerTurnToday: 1000,
  avgCostPerTurnToday: [{ currency: 'USD', amount: '0.30000000' }],
  avgTurnElapsedMsToday: 2000,
  degradedReasons: [{ reason: 'BUDGET', count: 1 }],
  sourceDegradations: [{ source: 'KNOWLEDGE', count: 3 }],
  databaseUsage: DATABASE_USAGE,
  databaseUsageError: null,
}

const OVERVIEW: ChatBiOverview = {
  startDate: '2026-09-27',
  endDate: '2026-10-03',
  answerTotal: 18,
  adoptionRate: null,
  userAccuracyRate: 0.75,
  systemAccuracyRate: 0.875,
  avgThinkingMs: 2250,
  hitRate: 0.8,
  failureRate: 0.05,
  daily: [
    {
      statDate: '2026-10-03',
      answerTotal: 11,
      adoptionRate: null,
      systemAccuracyRate: 0.8,
      hitRate: null,
      failureRate: 0.1,
      avgThinkingMs: 2400,
    },
  ],
}

function mountView() {
  return mount(OpsStatusView, {
    global: {
      plugins: [i18n],
      stubs: { AdminGate: { template: '<div data-testid="admin-gate"><slot /></div>' } },
    },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'zh-CN'
  adapter.fetchOpsStatus.mockReset().mockResolvedValue(STATUS)
  adapter.fetchChatBiOverview.mockReset().mockResolvedValue(OVERVIEW)
})

describe('OpsStatusView 与真实令牌闸门', () => {
  afterEach(() => {
    setChatTransport(undefined)
    setCredentialProvider(undefined)
  })

  it('未持令牌时不加载运维数据；提交令牌通过验证后才加载并渲染', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    setCredentialProvider(() => ({ adminToken: useKnowledgeStore().adminToken || undefined }))
    // 闸门用知识目录树验证令牌；这里只需要它放行。
    setChatTransport(async () =>
      Response.json({
        roots: [],
        index_status: {
          retrieval_mode: 'KEYWORD_ONLY',
          active_version: null,
          embedding_model: null,
          configured_model: null,
          stale: false,
          stale_reason: null,
          building: false,
          last_failure_reason: null,
        },
      }),
    )
    const wrapper = mount(OpsStatusView, { global: { plugins: [pinia, i18n] } })
    await flushPromises()

    expect(wrapper.find('[data-testid="admin-token-input"]').exists()).toBe(true)
    expect(adapter.fetchOpsStatus).not.toHaveBeenCalled()
    expect(adapter.fetchChatBiOverview).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="admin-token-input"]').setValue('admin-token-for-test')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(adapter.fetchOpsStatus).toHaveBeenCalledTimes(1)
    expect(adapter.fetchChatBiOverview).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="ops-budget"]').text()).toContain('ROLE:CUSTOMER')
    // 令牌不进页面内容。
    expect(wrapper.html()).not.toContain('admin-token-for-test')
  })
})

describe('OpsStatusView', () => {
  it('显示数据库表、连接数和待办箱，未配置存储上限时不显示进度', async () => {
    const wrapper = mountView()
    await flushPromises()

    const database = wrapper.get('[data-testid="ops-database"]')
    expect(database.text()).toContain('256 MB')
    expect(database.text()).toContain('2 / 7 / 100')
    expect(database.get('tbody tr').text()).toMatch(/memory_outbox.*2 KB.*暂无/)
    expect(database.get('[role="region"]').attributes()).toMatchObject({
      'aria-labelledby': 'ops-database-tables-title',
      tabindex: '0',
    })
    expect(database.get('#ops-database-connections-hint').text()).toContain('PostgreSQL 后端连接')
    expect(database.text()).toContain('未配置')
    expect(database.find('progress').exists()).toBe(false)
    expect(database.find('.ops__outbox-alert').exists()).toBe(false)
  })

  it.each([
    [0.79, null],
    [0.8, 'warn'],
    [0.95, 'danger'],
    [1.02, 'danger'],
  ])('按实际使用比例 %s 显示存储进度与状态', async (ratio, severity) => {
    adapter.fetchOpsStatus.mockResolvedValue({
      ...STATUS,
      databaseUsage: {
        ...DATABASE_USAGE,
        storageLimitBytes: 1024 ** 3,
        storageUsedRatio: ratio,
      },
    })
    const wrapper = mountView()
    await flushPromises()

    const database = wrapper.get('[data-testid="ops-database"]')
    expect(database.text()).toContain(`${Math.round(ratio * 100)}%`)
    const progress = database.get('progress')
    expect(progress.attributes('value')).toBe(String(Math.min(ratio, 1)))
    expect(progress.attributes('data-severity')).toBe(severity ?? undefined)
  })

  it.each([
    { failed: 1, oldestPendingAgeSeconds: null },
    { failed: 0, oldestPendingAgeSeconds: 1801 },
  ])('高亮有失败任务或积压超过 30 分钟的待办箱', async (outbox) => {
    adapter.fetchOpsStatus.mockResolvedValue({
      ...STATUS,
      databaseUsage: {
        ...DATABASE_USAGE,
        memoryOutbox: { ...DATABASE_USAGE.memoryOutbox, ...outbox },
      },
    })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('.ops__outbox-alert').text()).toContain('记忆待办箱需要关注')
  })

  it.each([
    ['TIMEOUT', 'zh-CN', '数据库用量读取失败（超时）'],
    ['UNAVAILABLE', 'en-US', 'Could not read database usage (unavailable)'],
    [null, 'zh-CN', '数据库用量读取失败（不可用）'],
  ] as const)('显示数据库读取失败原因 %s，保留运行状态', async (error, locale, expected) => {
    i18n.global.locale.value = locale
    adapter.fetchOpsStatus.mockResolvedValue({
      ...STATUS,
      databaseUsage: null,
      databaseUsageError: error,
    })
    const wrapper = mountView()
    await flushPromises()

    const database = wrapper.get('[data-testid="ops-database"]')
    expect(database.get('[role="status"]').text()).toBe(expected)
    expect(database.find('progress').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ops-runtime"]').exists()).toBe(true)
  })

  it('shows the three budget levels, cost, cache, tool errors, p95 and Chat BI', async () => {
    const wrapper = mountView()
    await flushPromises()

    const budget = wrapper.get('[data-testid="ops-budget"]').text()
    expect(budget).toContain('ROLE:CUSTOMER')
    expect(budget).toContain('SHOP:MERCHANT:1a2b3c4d')
    expect(wrapper.get('[data-testid="ops-cost"]').text()).toContain('0.75000000')
    expect(wrapper.get('[data-testid="ops-cost"]').text()).toContain('20%')
    expect(wrapper.get('[data-testid="ops-runtime"]').text()).toContain('10%')
    expect(wrapper.get('[data-testid="ops-routes"]').text()).toContain('/api/v2/merchant/chat')
    expect(wrapper.get('[data-testid="chatbi-overview"]').text()).toContain('18')
    expect(wrapper.findAll('[data-testid="chatbi-daily"] tbody tr')).toHaveLength(1)
  })

  it('shows per-turn tokens, cost and latency, and why turns degraded', async () => {
    const wrapper = mountView()
    await flushPromises()

    const turns = wrapper.get('[data-testid="ops-turns"]').text()
    expect(turns).toContain('1,000')
    expect(turns).toContain('0.30000000 USD')
    expect(turns).toContain('2,000')
    const reasons = wrapper.get('[data-testid="ops-degraded-reasons"]').text()
    expect(reasons).toContain('每日预算耗尽')
    expect(reasons).toContain('1')
    expect(wrapper.get('[data-testid="ops-source-degradations"]').text()).toContain('KNOWLEDGE')
  })

  it('says there is no per-turn data yet instead of showing zeros', async () => {
    adapter.fetchOpsStatus.mockResolvedValue({
      ...STATUS,
      turnsToday: 0,
      avgTokensPerTurnToday: null,
      avgCostPerTurnToday: [],
      avgTurnElapsedMsToday: null,
      degradedReasons: [],
      sourceDegradations: [],
    })
    const wrapper = mountView()
    await flushPromises()

    const turns = wrapper.get('[data-testid="ops-turns"]').text()
    expect(turns).toContain('暂无')
    expect(wrapper.find('[data-testid="ops-degraded-reasons"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="ops-source-degradations"]').exists()).toBe(false)
  })

  it('says unpriced calls are not zero cost', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[data-testid="ops-unpriced"]').text()).toContain('1')
  })

  it('a read-only token still sees Chat BI and is told ops status needs the admin token', async () => {
    adapter.fetchOpsStatus.mockRejectedValue(
      new AppError('FORBIDDEN', 'forbidden', { status: 403 }),
    )
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="ops-forbidden"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="ops-budget"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="chatbi-overview"]').text()).toContain('18')
  })

  it('has no write actions at all', async () => {
    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((button) => button.text())
    expect(labels.every((label) => label === i18n.global.t('opsStatus.refresh'))).toBe(true)
    expect(wrapper.html()).not.toMatch(/rollup|汇总回补|recompute/i)
  })

  it('renders an error without leaking details when loading fails', async () => {
    adapter.fetchOpsStatus.mockRejectedValue(new Error('postgresql://secret@db'))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[data-testid="ops-error"]').exists()).toBe(true)
    expect(wrapper.html()).not.toContain('postgresql')
  })
})
