import type { components } from '@/api/generated'
import type { ChatBiOverview, OpsStatus } from '@/types/opsStatus'

import { resolveTransport } from '../transport'

type S = components['schemas']

/**
 * 运维看板的 Adapter（N5 B Task 3，D-N5-1）：`/api/admin/ops/status` 与 Chat BI 概览。
 * 两者都走管理员令牌（`X-Admin-Token`）；只读令牌能读 Chat BI，读不了 ops/status（R6）。
 * 内部节点耗时（`agent_node_average_ms`）不进领域模型。
 */
export function toOpsStatus(raw: S['OpsStatusResponse']): OpsStatus {
  return {
    tokensUsedToday: raw.llm_tokens_used_today,
    tokensRemainingToday: raw.llm_tokens_remaining_today,
    callsToday: raw.llm_calls_today,
    rateLimitHits: raw.rate_limit_hits,
    degradedCount: raw.degraded_count,
    errorCodeCounts: { ...raw.error_code_counts },
    budgetLevels: raw.budget_levels.map((row) => ({
      level: row.level,
      scope: row.scope,
      budgetTokens: row.budget_tokens,
      usedTokens: row.used_tokens,
      remainingTokens: row.remaining_tokens,
    })),
    costToday: raw.llm_cost_today.map((row) => ({ currency: row.currency, amount: row.amount })),
    unpricedCallsToday: raw.unpriced_calls_today,
    cacheHitTokensToday: raw.cache_hit_tokens_today,
    cacheHitRateToday: raw.cache_hit_rate_today ?? null,
    toolCallsTotal: raw.tool_calls_total,
    toolErrorsTotal: raw.tool_errors_total,
    toolErrorRate: raw.tool_calls_total > 0 ? raw.tool_errors_total / raw.tool_calls_total : null,
    routeP95: Object.entries(raw.route_p95_ms)
      .map(([route, p95Ms]) => ({ route, p95Ms }))
      .sort((a, b) => b.p95Ms - a.p95Ms),
    demoDeploymentMode: raw.demo_deployment_mode,
    turnsToday: raw.turns_today,
    avgTokensPerTurnToday: raw.avg_tokens_per_turn_today ?? null,
    avgCostPerTurnToday: raw.avg_cost_per_turn_today.map((row) => ({
      currency: row.currency,
      amount: row.amount,
    })),
    avgTurnElapsedMsToday: raw.avg_turn_elapsed_ms_today ?? null,
    degradedReasons: Object.entries(raw.degraded_reason_counts)
      .map(([reason, count]) => ({ reason, count }))
      .sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason)),
    sourceDegradations: Object.entries(raw.source_degraded_counts)
      .map(([source, count]) => ({ source, count }))
      .sort((a, b) => b.count - a.count || a.source.localeCompare(b.source)),
  }
}

export function toChatBiOverview(raw: S['ChatBiOverviewResponse']): ChatBiOverview {
  return {
    startDate: raw.start_date,
    endDate: raw.end_date,
    answerTotal: raw.answer_total,
    adoptionRate: raw.adoption_rate ?? null,
    userAccuracyRate: raw.user_accuracy_rate ?? null,
    systemAccuracyRate: raw.system_accuracy_rate ?? null,
    avgThinkingMs: raw.avg_thinking_ms ?? null,
    hitRate: raw.hit_rate ?? null,
    failureRate: raw.failure_rate ?? null,
    daily: (raw.daily ?? []).map((day) => ({
      statDate: day.stat_date,
      answerTotal: day.answer_total,
      adoptionRate: day.adoption_rate ?? null,
      systemAccuracyRate: day.system_accuracy_rate ?? null,
      hitRate: day.hit_rate ?? null,
      failureRate: day.failure_rate ?? null,
      avgThinkingMs: day.avg_thinking_ms ?? null,
    })),
  }
}

export async function fetchOpsStatus(signal: AbortSignal): Promise<OpsStatus> {
  const transport = await resolveTransport()
  const response = await transport({ path: '/api/admin/ops/status', method: 'GET', auth: 'admin' }, signal)
  return toOpsStatus((await response.json()) as S['OpsStatusResponse'])
}

/** 运维看板上 Chat BI 概览的统计窗口长度（含今天）。 */
const CHATBI_OVERVIEW_DAYS = 7

function toDateParam(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/**
 * 截至 `today` 的最近 7 天（含当天），按浏览器本地日期取。
 * 看板显示的起止日期以后端回显为准，这里只负责给出必填的请求窗口。
 */
export function chatBiOverviewWindow(today: Date = new Date()): { startDate: string; endDate: string } {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (CHATBI_OVERVIEW_DAYS - 1))
  return { startDate: toDateParam(start), endDate: toDateParam(today) }
}

export async function fetchChatBiOverview(
  signal: AbortSignal,
  today: Date = new Date(),
): Promise<ChatBiOverview> {
  const transport = await resolveTransport()
  // 后端的 `start_date` / `end_date` 是必填 query，缺了直接 422。
  const window = chatBiOverviewWindow(today)
  const query = new URLSearchParams({ start_date: window.startDate, end_date: window.endDate })
  const response = await transport(
    { path: `/api/admin/analytics/chatbi/overview?${query.toString()}`, method: 'GET', auth: 'admin' },
    signal,
  )
  return toChatBiOverview((await response.json()) as S['ChatBiOverviewResponse'])
}
