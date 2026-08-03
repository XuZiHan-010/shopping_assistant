/**
 * Chat 领域模型。
 *
 * 后端契约是 snake_case（`docs/api.json`），组件只消费这里的 camelCase 模型。
 * 两者之间的唯一转换点是 `src/api/adapters/chat.ts`——组件不得直接引用
 * `generated.ts`，也不得自行做字段转换（前端方案 §5.0、§11）。
 *
 * 按模式必填的字段在这里一律是可选的：`CHAT`/`INVALID`/`RULE` 本来就没有指标和
 * 数据，把它们标成必填会逼着 Adapter 编造默认值，那正是 §5.0 明令禁止的。
 */
import type { components } from '@/api/generated'

export type AnswerMode = components['schemas']['AnswerMode']
export type QuestionCategory = components['schemas']['QuestionCategory']
export type QualityStatus = components['schemas']['QualityStatus']
export type AnalysisSource = components['schemas']['AnalysisSource']
export type MetricStatus = components['schemas']['MetricStatus']

/** SSE `step` 事件与 `thinking_steps` 同构。 */
export interface ThinkingStep {
  label: string
  node: string
}

/** 指标口径面板。PRD 要求来源、负责人、状态三项齐全，缺一前端只能显示空白。 */
export interface MetricDefinition {
  code: string
  displayName: string
  unit: string
  definition: string
  source: string
  owner: string
  status: MetricStatus
}

export interface ChartSeries {
  enabled: boolean
  type?: string
  allowedTypes: string[]
  title?: string
  dimensionKey?: string
  metricKey?: string
  unit?: string
  data: Array<Record<string, string | number | null>>
}

export interface Recommendation {
  title: string
  evidence: string
  action: string
}

export interface ExportInfo {
  id: string
  url: string
  expiresAt: string
}

/** 数据结果。无数据模式下整个对象为 undefined，而不是空壳。 */
export interface DataResult {
  rows: Array<Record<string, unknown>>
  totalRows: number
  truncated: boolean
  queryPlan?: string
}

/** 质量轨迹。降级信息属于这里，卡片必须显式展示（前端方案 §10）。 */
export interface QualityTrace {
  status: QualityStatus
  attempts: number
  notes: string[]
  sources: AnalysisSource[]
  degraded: boolean
  degradedReason?: string
}

/** 猜你想问。`alternates` 供「换一换」本地轮换，不额外发请求（§11）。 */
export interface SuggestedQuestions {
  current: string[]
  alternates: string[][]
}

export interface ChatAnswer {
  id: string
  sessionId: string
  answer: string
  mode: AnswerMode
  category?: QuestionCategory
  createdAt?: string
  thinkingSteps: ThinkingStep[]
  quality: QualityTrace
  suggestions: SuggestedQuestions
  metric?: MetricDefinition
  data?: DataResult
  chart?: ChartSeries
  recommendations: Recommendation[]
  export?: ExportInfo
}

/**
 * 消息状态。cancelled 与 error 刻意分开：用户主动取消不是故障，
 * UI 文案与是否提示重试都不同，混在一起会让每次取消都弹一次「出错了」。
 */
export type MessageStatus = 'pending' | 'streaming' | 'complete' | 'cancelled' | 'error'

export interface ChatMessage {
  localId: string
  id?: string
  /** 幂等键。入列时生成并常驻，重试路径直接从消息对象拿（前端方案 §5.9）。 */
  clientRequestId: string
  role: 'user' | 'assistant'
  text: string
  createdAt: string
  status: MessageStatus
  steps: ThinkingStep[]
  errorMessage?: string
  answer?: ChatAnswer
}
