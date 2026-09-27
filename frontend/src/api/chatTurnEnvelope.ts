/**
 * v1 `ChatResponse` 与 v2 `MerchantChatResponse` 共用的最终响应识别点
 * （`n2-merchant-vue-v2-migration` Task 6：「前端只保留一处最终响应解析」）。
 *
 * 两份契约的字段集合并不相同——v1 还带着指标口径、导出、图表、经营建议，
 * v2 目前只有 `answer` + `tool_calls`（N2 范围）——本函数只抽取两者都保证
 * 提供的公共子集：分析来源、思考步骤、质量与降级字段（§8.7.6
 * `DegradationMixin`）。跨两种模式复用的展示逻辑（降级徽标、来源标注）
 * 消费这份公共 envelope；v1 完整领域对象仍由 `toChatAnswer()`
 * （`adapters/chat.ts`）单独解析，本函数不取代它，只是两条流各自识别到
 * "这是最终响应" 时都要经过的同一个点。
 */
import type { components } from '@/api/generated'
import type { ThinkingStep } from '@/types/chat'

type QualityStatus = components['schemas']['QualityStatus']
type RawAnalysisSource = components['schemas']['AnalysisSource']

interface RawAnalysisSourceEntry {
  source: RawAnalysisSource
  degraded: boolean
  degraded_reason: string | null
}

/**
 * v1 `ChatResponse.analysis_sources` 是纯字符串数组（没有逐来源降级信息）；
 * v2 `MerchantChatResponse.analysis_sources` 是 `AnalysisSourceEntry[]`
 * （§8.7.6 补的逐来源降级能力，v1 没有）。两种形状都要能喂给同一个函数。
 */
type RawAnalysisSourcesField = RawAnalysisSource[] | RawAnalysisSourceEntry[]

/** v1 `ChatResponse` 与 v2 `MerchantChatResponse` 结构性兼容的公共子集。 */
export interface RawFinalResponse {
  answer: string
  analysis_sources: RawAnalysisSourcesField
  thinking_steps?: ThinkingStep[]
  quality_status: QualityStatus
  quality_attempts: number
  quality_notes?: string[]
  degraded: boolean
  degraded_reason: string | null
}

export interface AnalysisSourceView {
  source: string
  degraded: boolean
  degradedReason: string | null
}

export interface ChatTurnEnvelope {
  answer: string
  analysisSources: AnalysisSourceView[]
  thinkingSteps: ThinkingStep[]
  qualityStatus: QualityStatus
  qualityAttempts: number
  qualityNotes: string[]
  degraded: boolean
  degradedReason: string | null
}

function toAnalysisSourceView(
  entry: RawAnalysisSource | RawAnalysisSourceEntry,
): AnalysisSourceView {
  // v1 只给来源名字，没有逐项降级状态——归一为「未降级」，整轮降级仍由
  // 顶层 `degraded` 字段表达，不在这里编造一个 v1 没有的判断。
  if (typeof entry === 'string') return { source: entry, degraded: false, degradedReason: null }
  return { source: entry.source, degraded: entry.degraded, degradedReason: entry.degraded_reason }
}

export function parseFinalResponse(raw: RawFinalResponse): ChatTurnEnvelope {
  return {
    answer: raw.answer,
    analysisSources: raw.analysis_sources.map(toAnalysisSourceView),
    thinkingSteps: raw.thinking_steps ?? [],
    qualityStatus: raw.quality_status,
    qualityAttempts: raw.quality_attempts,
    qualityNotes: raw.quality_notes ?? [],
    degraded: raw.degraded,
    degradedReason: raw.degraded_reason,
  }
}

export interface ChatTurnView {
  turnDegraded: boolean
  sources: AnalysisSourceView[]
}

/**
 * 降级展示按「整轮 vs 单来源」分层（契约 §8.7.6）：整轮 `degraded=false` 但
 * 某个来源降级时，只在该来源旁标注，不把整条回答标成"已降级"。
 */
export function toTurnView(envelope: ChatTurnEnvelope): ChatTurnView {
  return { turnDegraded: envelope.degraded, sources: envelope.analysisSources }
}
