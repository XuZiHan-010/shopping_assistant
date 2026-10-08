import type { ChatTurn } from './chat'

export interface ConversationSummary {
  id: string
  title: string
  createdAt: string
  updatedAt: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  /** 助手消息的完整最终响应，与当轮 Chat 响应逐字段相同；提问消息为 `null`。 */
  turn: ChatTurn | null
}

export interface ConversationPage {
  items: ConversationSummary[]
  nextCursor: string | null
}
