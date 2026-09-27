/**
 * 顾客端会话目录（契约 §8.8）：列表、详情、删除。都需要顾客会话，
 * 归属由服务端按会话解析，前端只传 `conversation_id`。
 */
import type { ConversationMessage, ConversationPage } from '@/types/conversation'
import { toConversationMessage, toConversationSummary } from './adapters/conversations'
import { requestJson } from './client'
import { getSession } from './credentials'
import type { components } from './generated'
import { NoSessionError } from './shopApi'

type S = components['schemas']

/** 一次打开对话最多翻的消息页数；每页 100 条，超出部分不渲染并如实提示。 */
const MAX_MESSAGE_PAGES = 10
const MESSAGE_PAGE_SIZE = 100
export const MAX_HISTORY_MESSAGES = MAX_MESSAGE_PAGES * MESSAGE_PAGE_SIZE

function sessionId(): string {
  const session = getSession()
  if (!session) throw new NoSessionError()
  return session.sessionId
}

function withCursor(path: string, cursor: string | null, limit: number): string {
  const query = new URLSearchParams({ limit: String(limit) })
  if (cursor) query.set('cursor', cursor)
  return `${path}?${query.toString()}`
}

export async function listConversations(cursor: string | null = null): Promise<ConversationPage> {
  const page = await requestJson<S['CursorPage_ShopConversationSummary_']>(
    withCursor('/api/v2/shop/conversations', cursor, 20),
    { sessionId: sessionId() },
  )
  return { items: page.items.map(toConversationSummary), nextCursor: page.has_more ? page.next_cursor : null }
}

export interface ConversationHistory {
  messages: ConversationMessage[]
  /** 超过翻页上限仍有后续消息时为 true。 */
  truncated: boolean
}

/** 按 `created_at ASC` 逐页取完一段对话的消息（有上限）。 */
export async function getConversationHistory(conversationId: string): Promise<ConversationHistory> {
  const path = `/api/v2/shop/conversations/${encodeURIComponent(conversationId)}`
  const messages: ConversationMessage[] = []
  let cursor: string | null = null
  for (let pageIndex = 0; pageIndex < MAX_MESSAGE_PAGES; pageIndex += 1) {
    const detail: S['ShopConversationDetailResponse'] = await requestJson(withCursor(path, cursor, MESSAGE_PAGE_SIZE), {
      sessionId: sessionId(),
    })
    messages.push(...detail.messages.items.map(toConversationMessage))
    if (!detail.messages.has_more || !detail.messages.next_cursor) return { messages, truncated: false }
    cursor = detail.messages.next_cursor
  }
  return { messages, truncated: true }
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await requestJson<void>(`/api/v2/shop/conversations/${encodeURIComponent(conversationId)}`, {
    method: 'DELETE',
    sessionId: sessionId(),
  })
}
