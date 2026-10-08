import { afterEach, describe, expect, it } from 'vitest'

import type { components } from '@/api/generated'
import { setChatTransport } from '@/api/transport'

import { chatBiOverviewWindow, fetchChatBiOverview, toChatBiOverview, toOpsStatus } from './adminOps'

type S = components['schemas']

const RAW_STATUS: S['OpsStatusResponse'] = {
  llm_tokens_used_today: 1200,
  llm_tokens_remaining_today: 3800,
  llm_calls_today: 4,
  rate_limit_hits: 2,
  degraded_count: 1,
  error_code_counts: { RATE_LIMITED: 2 },
  agent_node_average_ms: { understand: 12.5 },
  demo_deployment_mode: true,
  budget_levels: [
    { level: 'GLOBAL', scope: 'GLOBAL', budget_tokens: 5000, used_tokens: 1200, remaining_tokens: 3800 },
    { level: 'SHOP', scope: 'SHOP:MERCHANT:1a2b3c4d', budget_tokens: 1000, used_tokens: 1000, remaining_tokens: 0 },
  ],
  llm_cost_today: [{ currency: 'USD', amount: '0.75000000' }],
  unpriced_calls_today: 1,
  cache_hit_tokens_today: 400,
  cache_hit_rate_today: 0.2,
  tool_calls_total: 10,
  tool_errors_total: 1,
  route_p95_ms: { '/api/health': 3, '/api/v2/merchant/chat': 1800 },
  turns_today: 2,
  avg_tokens_per_turn_today: 1000,
  avg_cost_per_turn_today: [{ currency: 'USD', amount: '0.30000000' }],
  avg_turn_elapsed_ms_today: 2000,
  degraded_reason_counts: { BUDGET: 2, LIMIT: 5 },
  source_degraded_counts: { KNOWLEDGE: 1 },
}

describe('toOpsStatus', () => {
  it('maps the ops snapshot and derives the tool error rate', () => {
    const status = toOpsStatus(RAW_STATUS)

    expect(status.budgetLevels[1]).toEqual({
      level: 'SHOP', scope: 'SHOP:MERCHANT:1a2b3c4d', budgetTokens: 1000, usedTokens: 1000, remainingTokens: 0,
    })
    expect(status.costToday).toEqual([{ currency: 'USD', amount: '0.75000000' }])
    expect(status.toolErrorRate).toBeCloseTo(0.1)
    expect(status.cacheHitRateToday).toBe(0.2)
    expect(status.unpricedCallsToday).toBe(1)
  })

  it('sorts routes by p95 descending and has no error rate before any tool call', () => {
    const status = toOpsStatus({ ...RAW_STATUS, tool_calls_total: 0, tool_errors_total: 0 })

    expect(status.routeP95.map((row) => row.route)).toEqual(['/api/v2/merchant/chat', '/api/health'])
    expect(status.toolErrorRate).toBeNull()
  })

  it('maps per-turn averages and sorts degradation reasons by count', () => {
    const status = toOpsStatus(RAW_STATUS)

    expect(status.turnsToday).toBe(2)
    expect(status.avgTokensPerTurnToday).toBe(1000)
    expect(status.avgCostPerTurnToday).toEqual([{ currency: 'USD', amount: '0.30000000' }])
    expect(status.avgTurnElapsedMsToday).toBe(2000)
    expect(status.degradedReasons).toEqual([
      { reason: 'LIMIT', count: 5 },
      { reason: 'BUDGET', count: 2 },
    ])
    expect(status.sourceDegradations).toEqual([{ source: 'KNOWLEDGE', count: 1 }])
  })

  it('keeps missing per-turn averages as null instead of zero', () => {
    const status = toOpsStatus({
      ...RAW_STATUS,
      turns_today: 0,
      avg_tokens_per_turn_today: null,
      avg_cost_per_turn_today: [],
      avg_turn_elapsed_ms_today: null,
      degraded_reason_counts: {},
      source_degraded_counts: {},
    })

    expect(status.avgTokensPerTurnToday).toBeNull()
    expect(status.avgTurnElapsedMsToday).toBeNull()
    expect(status.avgCostPerTurnToday).toEqual([])
    expect(status.degradedReasons).toEqual([])
  })

  it('does not carry internal node timings into the domain model', () => {
    expect('agentNodeAverageMs' in toOpsStatus(RAW_STATUS)).toBe(false)
  })
})

describe('toChatBiOverview', () => {
  it('maps rates and keeps nulls as missing data', () => {
    const overview = toChatBiOverview({
      start_date: '2026-09-27', end_date: '2026-10-03', answer_total: 18, business_question_total: 15,
      feedback_total: 7, thinking_sample_count: 16, adoption_rate: null, user_accuracy_rate: 0.75,
      system_accuracy_rate: 0.875, avg_thinking_ms: 2250, hit_rate: 0.8, failure_rate: 0.05,
      daily: [{
        stat_date: '2026-10-03', answer_total: 11, adoption_rate: null, user_accuracy_rate: 0.75,
        system_accuracy_rate: 0.8, avg_thinking_ms: 2400, hit_rate: null, failure_rate: 0.1,
      }],
    })

    expect(overview.adoptionRate).toBeNull()
    expect(overview.daily[0]).toMatchObject({ statDate: '2026-10-03', answerTotal: 11, hitRate: null })
  })
})

describe('chatBiOverviewWindow', () => {
  it('covers the last 7 days including today', () => {
    expect(chatBiOverviewWindow(new Date(2026, 9, 7, 15, 30))).toEqual({
      startDate: '2026-10-01',
      endDate: '2026-10-07',
    })
  })

  it('crosses month boundaries and pads single-digit months and days', () => {
    expect(chatBiOverviewWindow(new Date(2026, 2, 3))).toEqual({
      startDate: '2026-02-25',
      endDate: '2026-03-03',
    })
  })
})

describe('fetchChatBiOverview', () => {
  afterEach(() => {
    setChatTransport(undefined)
  })

  it('always sends the start_date and end_date the backend requires', async () => {
    // 后端的 `start_date` / `end_date` 是必填 query；缺了就是 422，看板只剩「加载失败」。
    const paths: string[] = []
    setChatTransport(async (request) => {
      paths.push(request.path)
      return Response.json({
        start_date: '2026-10-01', end_date: '2026-10-07', answer_total: 0, business_question_total: 0,
        feedback_total: 0, thinking_sample_count: 0, adoption_rate: null, user_accuracy_rate: null,
        system_accuracy_rate: null, avg_thinking_ms: null, hit_rate: null, failure_rate: null, daily: [],
      } satisfies S['ChatBiOverviewResponse'])
    })

    await fetchChatBiOverview(new AbortController().signal, new Date(2026, 9, 7))

    expect(paths).toEqual([
      '/api/admin/analytics/chatbi/overview?start_date=2026-10-01&end_date=2026-10-07',
    ])
  })
})
