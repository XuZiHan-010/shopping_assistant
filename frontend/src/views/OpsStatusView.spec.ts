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
    { level: 'GLOBAL', scope: 'GLOBAL', budgetTokens: 5000, usedTokens: 1200, remainingTokens: 3800 },
    { level: 'ROLE', scope: 'ROLE:CUSTOMER', budgetTokens: 2000, usedTokens: 200, remainingTokens: 1800 },
    { level: 'SHOP', scope: 'SHOP:MERCHANT:1a2b3c4d', budgetTokens: 1000, usedTokens: 1000, remainingTokens: 0 },
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
      statDate: '2026-10-03', answerTotal: 11, adoptionRate: null, systemAccuracyRate: 0.8,
      hitRate: null, failureRate: 0.1, avgThinkingMs: 2400,
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
          retrieval_mode: 'KEYWORD_ONLY', active_version: null, embedding_model: null,
          configured_model: null, stale: false, stale_reason: null, building: false,
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
    adapter.fetchOpsStatus.mockRejectedValue(new AppError('FORBIDDEN', 'forbidden', { status: 403 }))
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
