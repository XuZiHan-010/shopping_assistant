import type { AnalysisSource, ChatTurn, ToolCall } from '@/types/chat'
import type { components } from '../generated'

type S = components['schemas']

export function toToolCall(raw: S['ToolCallDisplay']): ToolCall {
  // 显式挑字段：即使后端将来多带了内部字段，也不会流到界面。
  return { toolName: raw.tool_name, callId: raw.call_id, status: raw.status, summary: raw.summary }
}

function toSource(raw: S['AnalysisSourceEntry']): AnalysisSource {
  return { source: raw.source, degraded: raw.degraded, degradedReason: raw.degraded_reason }
}

export function toChatTurn(raw: S['ShopChatResponse']): ChatTurn {
  return {
    id: raw.id,
    conversationId: raw.conversation_id,
    answer: raw.answer,
    toolCalls: raw.tool_calls.map(toToolCall),
    analysisSources: raw.analysis_sources.map(toSource),
    qualityStatus: raw.quality_status,
    qualityNotes: raw.quality_notes ?? [],
    degraded: raw.degraded,
    degradedReason: raw.degraded_reason,
    answerMode: raw.answer_mode,
    suggestions: raw.suggestions ?? [],
    createdAt: raw.created_at,
  }
}
