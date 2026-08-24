/**
 * Chat BI 看板的前端领域模型。
 *
 * 六项指标均允许为 `null`。这不是零，而是汇总样本不足；组件必须渲染可见的
 * 「样本不足」状态，不能将其伪装成 0%。
 */
export interface NorthStarMetrics {
  adoptionRate: number | null
  userAccuracyRate: number | null
  systemAccuracyRate: number | null
  avgThinkingMs: number | null
  hitRate: number | null
  failureRate: number | null
}

export interface ChatBiDailyPoint {
  statDate: string
  answerTotal: number
  metrics: NorthStarMetrics
}

export interface ChatBiOverview {
  startDate: string
  endDate: string
  answerTotal: number
  businessQuestionTotal: number
  feedbackTotal: number
  thinkingSampleCount: number
  metrics: NorthStarMetrics
  daily: ChatBiDailyPoint[]
}

export interface ChatBiCategoryRow {
  category: string
  displayName: string
  answerTotal: number
  metrics: NorthStarMetrics
}
