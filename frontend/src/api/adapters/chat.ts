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

import type { components } from '@/api/generated'
import type {
  ChartSeries,
  ChatAnswer,
  DataResult,
  ExportInfo,
  MetricDefinition,
  QualityTrace,
  Recommendation,
  SuggestedQuestions,
  ThinkingStep,
} from '@/types/chat'

type RawChatResponse = components['schemas']['ChatResponse']

/** 载荷违反后端契约时抛出，消息可直接展示给用户。 */
export class ChatContractError extends Error {
  constructor(message: string) {
    super(message)
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

const NO_SOURCE_MODES = new Set(['CHAT', 'INVALID'])
const METRIC_FIELDS = [
  'metric_code',
  'metric_display_name',
  'metric_unit',
  'metric_definition',
  'metric_source',
  'metric_owner',
  'metric_status',
] as const

/**
 * 只覆盖语义不变量，字段形状交给 `generated.ts`。
 * `.loose()` 让未列出的字段原样通过——后端加字段不该让前端崩掉。
 */
const semanticGuard = z
  .object({
    answer: z.string().trim().min(1, '回答正文为空，后端返回了不完整的结果'),
    answer_mode: z.enum(ANSWER_MODES, { message: 'answer_mode 不在约定的取值范围内' }),
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

    if (hasNone && sources.length > 1) {
      fail('analysis_sources 中的 NONE 只能单独出现')
    }
    if (NO_SOURCE_MODES.has(value.answer_mode)) {
      if (!hasNone || sources.length > 1) {
        fail(`${value.answer_mode} 模式的 analysis_sources 必须是 ["NONE"]`)
      }
      if (value.degraded) {
        fail(`${value.answer_mode} 模式不应标记为降级`)
      }
    }
    if (sources.includes('FALLBACK') && !value.degraded) {
      fail('含 FALLBACK 来源时 degraded 必须为 true')
    }
    if (value.degraded && !value.degraded_reason) {
      fail('降级回答必须说明 degraded_reason')
    }
  })

/** METRIC 的按模式必填校验单独放，好给出指名道姓的错误。 */
function assertMetricContract(raw: RawChatResponse): void {
  if (raw.answer_mode !== 'METRIC') return

  for (const field of METRIC_FIELDS) {
    if (raw[field] === null || raw[field] === undefined) {
      throw new ChatContractError(`METRIC 回答缺少 ${field}，指标口径面板会显示空白`)
    }
  }
  if (!raw.visualization) {
    throw new ChatContractError('METRIC 回答缺少 visualization')
  }
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
function toMetric(raw: RawChatResponse): MetricDefinition | undefined {
  if (
    raw.metric_code == null ||
    raw.metric_display_name == null ||
    raw.metric_unit == null ||
    raw.metric_definition == null ||
    raw.metric_source == null ||
    raw.metric_owner == null ||
    raw.metric_status == null
  ) {
    return undefined
  }
  return {
    code: raw.metric_code,
    displayName: raw.metric_display_name,
    unit: raw.metric_unit,
    definition: raw.metric_definition,
    source: raw.metric_source,
    owner: raw.metric_owner,
    status: raw.metric_status,
  }
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
  assertMetricContract(raw)

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
    metric: toMetric(raw),
    data: toData(raw),
    chart: toChart(raw),
    recommendations: toRecommendations(raw),
    export: toExport(raw),
  }
}
