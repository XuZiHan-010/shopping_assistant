import type { ConversationMessage, ConversationSummary } from '@/types/conversation'
import type { components } from '../generated'
import { toChatTurn } from './chat'

type S = components['schemas']

export function toConversationSummary(raw: S['ShopConversationSummary']): ConversationSummary {
  return { id: raw.id, title: raw.title, createdAt: raw.created_at, updatedAt: raw.updated_at }
}

/** 历史回答复用 Chat 的同一个 Adapter：详情里的 `answer` 与当轮响应同形，不另写一套解析。 */
export function toConversationMessage(raw: S['ShopConversationMessage']): ConversationMessage {
  return {
    id: raw.id,
    role: raw.role,
    content: raw.content,
    createdAt: raw.created_at,
    turn: raw.answer ? toChatTurn(raw.answer) : null,
  }
}
