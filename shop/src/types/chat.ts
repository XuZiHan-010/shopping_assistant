export type ToolStatus = 'STARTED' | 'RUNNING' | 'SUCCEEDED' | 'DEGRADED' | 'FAILED' | 'UNAVAILABLE'

/** 只含展示信息：工具名、状态、摘要。不含参数或结果（契约 §8.7.5 脱敏）。 */
export interface ToolCall {
  toolName: string
  callId: string
  status: ToolStatus
  summary: string
}

export interface AnalysisSource {
  source: string
  degraded: boolean
  degradedReason: string | null
}

export interface ChatTurn {
  id: string
  conversationId: string
  answer: string
  toolCalls: ToolCall[]
  analysisSources: AnalysisSource[]
  qualityStatus: 'PASSED' | 'DEGRADED' | 'FAILED' | 'NOT_RUN'
  qualityNotes: string[]
  degraded: boolean
  degradedReason: string | null
  answerMode: string
  suggestions: string[]
  createdAt: string
}
