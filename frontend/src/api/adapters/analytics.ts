import type { components } from '@/api/generated'
import type { ChatBiCategoryRow, ChatBiOverview, NorthStarMetrics } from '@/types/analytics'

type OverviewPayload = components['schemas']['ChatBiOverviewResponse']
type CategoriesPayload = components['schemas']['ChatBiCategoriesResponse']

/** 六项指标的 snake_case → camelCase 映射只保留在此处，供总览、趋势和分类复用。 */
function toMetrics(source: {
  adoption_rate: number | null
  user_accuracy_rate: number | null
  system_accuracy_rate: number | null
  avg_thinking_ms: number | null
  hit_rate: number | null
  failure_rate: number | null
}): NorthStarMetrics {
  return {
    adoptionRate: source.adoption_rate,
    userAccuracyRate: source.user_accuracy_rate,
    systemAccuracyRate: source.system_accuracy_rate,
    avgThinkingMs: source.avg_thinking_ms,
    hitRate: source.hit_rate,
    failureRate: source.failure_rate,
  }
}

export function toChatBiOverview(payload: OverviewPayload): ChatBiOverview {
  return {
    startDate: payload.start_date,
    endDate: payload.end_date,
    answerTotal: payload.answer_total,
    businessQuestionTotal: payload.business_question_total,
    feedbackTotal: payload.feedback_total,
    thinkingSampleCount: payload.thinking_sample_count,
    metrics: toMetrics(payload),
    daily: (payload.daily ?? []).map((point) => ({
      statDate: point.stat_date,
      answerTotal: point.answer_total,
      metrics: toMetrics(point),
    })),
  }
}

export function toChatBiCategories(payload: CategoriesPayload): ChatBiCategoryRow[] {
  return (payload.items ?? []).map((item) => ({
    category: item.category,
    displayName: item.category_display_name,
    answerTotal: item.answer_total,
    metrics: toMetrics(item),
  }))
}
