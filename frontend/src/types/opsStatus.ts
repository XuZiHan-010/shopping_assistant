/**
 * 只读运维看板的领域模型（N5 B Task 3，PRD §10.4、§14，D-N5-1）。
 *
 * 只收运维聚合：预算、成本、限流、降级、工具错误率、耗时与 Chat BI 概览。
 * 不含任何 Token、Prompt、经营数据或请求正文；店铺级预算只有后端给的脱敏标识。
 */

export type BudgetLevelKind = 'GLOBAL' | 'ROLE' | 'SHOP'

export interface BudgetLevel {
  level: BudgetLevelKind
  scope: string
  budgetTokens: number
  usedTokens: number
  remainingTokens: number
}

export interface CostAmount {
  currency: string
  /** 十进制字符串，原样展示，不转浮点。 */
  amount: string
}

export interface RouteLatency {
  route: string
  p95Ms: number
}

export interface DegradedReasonCount {
  /** 后端原因码（`UPSTREAM`、`BUDGET`、`LIMIT`…）；界面按码查文案，查不到就显示原码。 */
  reason: string
  count: number
}

export interface SourceDegradationCount {
  source: string
  count: number
}

export interface OpsStatus {
  tokensUsedToday: number
  tokensRemainingToday: number
  callsToday: number
  rateLimitHits: number
  degradedCount: number
  errorCodeCounts: Record<string, number>
  budgetLevels: BudgetLevel[]
  costToday: CostAmount[]
  unpricedCallsToday: number
  cacheHitTokensToday: number
  cacheHitRateToday: number | null
  toolCallsTotal: number
  toolErrorsTotal: number
  /** 还没有工具调用时为 null，界面显示「暂无」而不是 0%。 */
  toolErrorRate: number | null
  routeP95: RouteLatency[]
  /** 当日发生过模型调用的回合数；三个「每回合」平均值在没有回合时为 null / 空，不显示成 0。 */
  turnsToday: number
  avgTokensPerTurnToday: number | null
  avgCostPerTurnToday: CostAmount[]
  avgTurnElapsedMsToday: number | null
  /** 整轮降级按原因计数（进程启动以来），按次数降序。 */
  degradedReasons: DegradedReasonCount[]
  /** 回答没有整轮降级、但某个来源降级的次数，按来源。 */
  sourceDegradations: SourceDegradationCount[]
  demoDeploymentMode: boolean
}

export interface ChatBiDaily {
  statDate: string
  answerTotal: number
  adoptionRate: number | null
  systemAccuracyRate: number | null
  hitRate: number | null
  failureRate: number | null
  avgThinkingMs: number | null
}

export interface ChatBiOverview {
  startDate: string
  endDate: string
  answerTotal: number
  adoptionRate: number | null
  userAccuracyRate: number | null
  systemAccuracyRate: number | null
  avgThinkingMs: number | null
  hitRate: number | null
  failureRate: number | null
  daily: ChatBiDaily[]
}
