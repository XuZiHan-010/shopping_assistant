/**
 * `ChatResponse` → 领域模型的唯一转换点（前端方案 §5.0、§11）。
 *
 * 字段**形状**由 `generated.ts` 保证，这里不重复声明——复制一遍就成了第二套契约，
 * 后端一改就有两处要同步。zod 在这里只守**语义不变量**：那些类型系统表达不了、
 * 但后端契约（`docs/backend-development-plan.md` §8.2）明确要求的组合约束。
 *
 * 这组守卫在 F2 还有第二个用途：挡住 Mock 造出后端不可能产生的载荷。
 */
import { z } from 'zod'

import { AppError } from '@/api/errors'
import type { components } from '@/api/generated'
import type {
  ChartSeries,
  ChatAnswer,
  DataResult,
  ExportInfo,
  FeedbackState,
  MetricDefinition,
  QualityTrace,
  Recommendation,
  SuggestedQuestions,
  ThinkingStep,
} from '@/types/chat'

type RawChatResponse = components['schemas']['ChatResponse']
type RawConversationAnswerPayload = components['schemas']['ConversationAnswerPayload']

/**
 * 载荷违反后端契约时抛出，消息可直接展示给用户。
 * 是 `AppError` 的 `CONTRACT` 特化——契约违反是前后端之一的缺陷，必须上报。
 */
export class ChatContractError extends AppError {
  constructor(message: string) {
    super('CONTRACT', message, { shouldReport: true })
    this.name = 'ChatContractError'
  }
}

const ANSWER_MODES = [
  'METRIC',
  'DETAIL',
  'RULE',
  'IDENTITY',
  'CHAT',
  'INVALID',
  'ATTACHMENT',
] as const

const ANALYSIS_SOURCES = [
  'DATABASE',
  'KNOWLEDGE',
  'ATTACHMENT',
  'MEMORY',
  'FALLBACK',
  'NONE',
] as const

const METRIC_FIELDS = [
  'metric_code',
  'metric_display_name',
  'metric_unit',
  'metric_definition',
  'metric_sql_definition',
  'metric_dimensions',
  'metric_source_database',
  'metric_source_table',
  'metric_source',
  'metric_generated',
  'metric_owner',
  'metric_status',
] as const

/**
 * 只覆盖语义不变量，字段形状交给 `generated.ts`。
 * `.loose()` 让未列出的字段原样通过——后端加字段不该让前端崩掉。
 */
const semanticGuard = z
  .object({
    answer: z.string(),
    answer_mode: z.enum(ANSWER_MODES, { message: 'answer_mode 不在约定的取值范围内' }),
    recommendations: z.array(z.unknown()).nullable().optional(),
    analysis_sources: z
      .array(z.enum(ANALYSIS_SOURCES, { message: 'analysis_sources 含未知来源' }))
      .min(1, 'analysis_sources 至少要有一个元素'),
    quality_attempts: z
      .number()
      .int()
      .min(0, 'quality_attempts 不能为负')
      .max(2, 'quality_attempts 最多为 2'),
    degraded: z.boolean(),
    degraded_reason: z.string().nullable().optional(),
  })
  .loose()
  .superRefine((value, ctx) => {
    const fail = (message: string) => ctx.addIssue({ code: 'custom', message })
    const sources = value.analysis_sources
    const hasNone = sources.includes('NONE')
    const recommendations = value.recommendations ?? []
    const isTableOnlyDetail = value.answer_mode === 'DETAIL' && value.answer === ''

    if (isTableOnlyDetail && recommendations.length > 0) {
      fail('纯明细不得提供 recommendations')
    }
    if (value.answer_mode === 'DETAIL' && value.answer !== '' && !value.answer.trim()) {
      fail('纯明细 answer 必须为精确空字符串')
    }
    if (!isTableOnlyDetail && !value.answer.trim()) {
      fail('非纯明细的回答正文不能为空')
    }
    if (value.answer_mode === 'DETAIL' && value.answer !== '' && recommendations.length < 2) {
      fail('带分析正文的 DETAIL 至少需要两条 recommendations')
    }

    if (hasNone && sources.length > 1) {
      fail('analysis_sources 中的 NONE 只能单独出现')
    }
    if (value.answer_mode === 'INVALID') {
      if (!hasNone || sources.length > 1) {
        fail('INVALID 模式的 analysis_sources 必须是 ["NONE"]')
      }
      if (value.degraded) {
        fail('INVALID 模式不应标记为降级')
      }
    }
    if (value.answer_mode === 'CHAT' && !value.degraded && (!hasNone || sources.length > 1)) {
      fail('未降级的 CHAT 模式的 analysis_sources 必须是 ["NONE"]')
    }
    if (
      value.answer_mode === 'CHAT' &&
      value.degraded &&
      (sources.length !== 1 || sources[0] !== 'FALLBACK')
    ) {
      fail('降级的 CHAT 模式的 analysis_sources 必须是 ["FALLBACK"]')
    }
    if (sources.includes('FALLBACK') && !value.degraded) {
      fail('含 FALLBACK 来源时 degraded 必须为 true')
    }
    if (value.degraded && !value.degraded_reason) {
      fail('降级回答必须说明 degraded_reason')
    }
  })

/**
 * METRIC 的按模式必填字段单独校验，但**不抛异常**——缺一个面板不该拖垮整条回答。
 * 收集到的提示进 `ChatAnswer.contractWarnings`，由 UI 决定怎么展示空状态。
 * 真正的契约破坏（语义不变量）仍然由 `semanticGuard` 抛 `ChatContractError`。
 */
function collectMetricWarnings(raw: RawChatResponse): string[] {
  if (raw.answer_mode !== 'METRIC') return []

  const missing = METRIC_FIELDS.filter((field) => raw[field] === null || raw[field] === undefined)
  const warnings = missing.length
    ? [`METRIC 回答缺少 ${missing.join('、')}，指标口径面板将显示空状态`]
    : []
  if (!raw.visualization) {
    warnings.push('METRIC 回答缺少 visualization，图表面板将显示空状态')
  }
  return warnings
}

function toThinkingSteps(raw: RawChatResponse): ThinkingStep[] {
  return (raw.thinking_steps ?? []).map((step) => ({ label: step.label, node: step.node }))
}

function toQuality(raw: RawChatResponse): QualityTrace {
  return {
    status: raw.quality_status,
    attempts: raw.quality_attempts,
    notes: raw.quality_notes ?? [],
    sources: raw.analysis_sources,
    degraded: raw.degraded,
    degradedReason: raw.degraded_reason ?? undefined,
  }
}

function toSuggestions(raw: RawChatResponse): SuggestedQuestions {
  return {
    current: raw.suggestions ?? [],
    alternates: raw.suggestion_alternates ?? [],
  }
}

/** 按模式缺省时返回 undefined，绝不编造默认值（§5.0）。 */
function toMetric(raw: RawChatResponse, warnings: string[]): MetricDefinition | undefined {
  if (
    raw.metric_code == null ||
    raw.metric_display_name == null ||
    raw.metric_unit == null ||
    raw.metric_definition == null ||
    raw.metric_sql_definition == null ||
    raw.metric_dimensions == null ||
    raw.metric_source_database == null ||
    raw.metric_source_table == null ||
    raw.metric_source == null ||
    raw.metric_generated == null ||
    raw.metric_owner == null ||
    raw.metric_status == null
  ) {
    return undefined
  }
  const reportUrl = toSafeReportUrl(raw.metric_report_url, warnings)
  return {
    code: raw.metric_code,
    displayName: raw.metric_display_name,
    unit: raw.metric_unit,
    definition: raw.metric_definition,
    sqlDefinition: raw.metric_sql_definition,
    dimensions: raw.metric_dimensions,
    sourceDatabase: raw.metric_source_database,
    sourceTable: raw.metric_source_table,
    reportUrl,
    source: raw.metric_source,
    generated: raw.metric_generated,
    notice: raw.metric_notice ?? undefined,
    owner: raw.metric_owner,
    status: raw.metric_status,
  }
}

function toSafeReportUrl(value: string | null | undefined, warnings: string[]): string | undefined {
  if (value == null) return undefined
  try {
    const url = new URL(value)
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.href
  } catch {
    // 不把不安全或相对 URL 交给组件渲染。
  }
  warnings.push('metric_report_url 不是安全的 HTTP/HTTPS 绝对链接，已隐藏。')
  return undefined
}

function toData(raw: RawChatResponse): DataResult | undefined {
  if (raw.data_rows == null || raw.total_rows == null || raw.truncated == null) {
    return undefined
  }
  return {
    rows: raw.data_rows,
    totalRows: raw.total_rows,
    truncated: raw.truncated,
    queryPlan: raw.query_plan?.summary,
  }
}

function toChart(raw: RawChatResponse): ChartSeries | undefined {
  const visualization = raw.visualization
  if (!visualization) return undefined
  return {
    enabled: visualization.enabled,
    type: visualization.type ?? undefined,
    allowedTypes: visualization.allowed_types ?? [],
    title: visualization.title ?? undefined,
    dimensionKey: visualization.dimension_key ?? undefined,
    metricKey: visualization.metric_key ?? undefined,
    unit: visualization.unit ?? undefined,
    data: visualization.data ?? [],
  }
}

function toRecommendations(raw: RawChatResponse): Recommendation[] {
  return (raw.recommendations ?? []).map((item) => ({
    title: item.title,
    evidence: item.evidence,
    action: item.action,
  }))
}

function toExport(raw: RawChatResponse): ExportInfo | undefined {
  if (!raw.export) return undefined
  return {
    id: raw.export.id,
    url: raw.export.url,
    expiresAt: raw.export.expires_at,
  }
}

export function toChatAnswer(raw: RawChatResponse): ChatAnswer {
  const parsed = semanticGuard.safeParse(raw)
  if (!parsed.success) {
    const reasons = parsed.error.issues.map((issue) => issue.message).join('；')
    throw new ChatContractError(`回答不符合后端契约：${reasons}`)
  }
  const contractWarnings = collectMetricWarnings(raw)

  return {
    id: raw.id,
    sessionId: raw.session_id,
    answer: raw.answer,
    mode: raw.answer_mode,
    category: raw.category ?? undefined,
    createdAt: raw.created_at,
    thinkingSteps: toThinkingSteps(raw),
    quality: toQuality(raw),
    suggestions: toSuggestions(raw),
    metric: toMetric(raw, contractWarnings),
    data: toData(raw),
    chart: toChart(raw),
    recommendations: toRecommendations(raw),
    export: toExport(raw),
    contractWarnings,
  }
}

/** 会话详情的脱敏助手载荷 → 领域回答；不能复用完整 ChatResponse 的校验器。 */
export function toConversationAnswer(
  raw: RawConversationAnswerPayload,
  context: { sessionId: string; content: string; createdAt: string },
): ChatAnswer {
  const { sessionId, content, createdAt } = context
  const hasTableMetadata = raw.total_rows != null && raw.truncated != null
  return {
    id: raw.answer_id,
    sessionId,
    answer: content,
    mode: raw.answer_mode,
    createdAt,
    thinkingSteps: raw.thinking_steps ?? [],
    quality: {
      status: raw.quality_status,
      attempts: raw.quality_attempts,
      notes: raw.quality_notes ?? [],
      // 详情载荷未保存 analysis_sources。历史消息不能伪造来源，质量区只呈现
      // 可由服务端确认的状态与备注。
      sources: [],
      degraded: raw.degraded,
      degradedReason: raw.degraded_reason ?? undefined,
    },
    suggestions: { current: [], alternates: [] },
    data: hasTableMetadata
      ? {
          rows: [],
          columns: raw.columns ?? [],
          totalRows: raw.total_rows!,
          truncated: raw.truncated!,
        }
      : undefined,
    recommendations: [],
    contractWarnings: [],
  }
}

/** 反馈请求保持完整覆盖语义，reaction 为 null 时也必须显式发送。 */
export function toFeedbackRequestPayload(
  state: FeedbackState,
): components['schemas']['FeedbackRequest'] {
  return {
    is_adopted: state.isAdopted,
    reaction: state.reaction,
  }
}

export function toFeedbackState(raw: components['schemas']['FeedbackResponse']): FeedbackState {
  return {
    isAdopted: raw.is_adopted,
    reaction: raw.reaction,
  }
}
