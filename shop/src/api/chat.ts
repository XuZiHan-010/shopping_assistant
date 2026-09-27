import type { ChatStreamEvent } from './sse'
import { parseSse } from './sse'
import { rawRequest } from './client'
import { getSession } from './credentials'
import { NoSessionError } from './shopApi'

export interface SendChatInput {
  clientRequestId: string
  message: string
  conversationId?: string | null
  signal?: AbortSignal
}

/** 发送一轮顾客导购消息，返回事件流；流以 `turn_complete` 或 `error` 收尾。 */
export async function* streamShopChat(input: SendChatInput): AsyncGenerator<ChatStreamEvent> {
  const session = getSession()
  if (!session) throw new NoSessionError()
  const response = await rawRequest('/api/v2/shop/chat', {
    method: 'POST',
    body: {
      client_request_id: input.clientRequestId,
      message: input.message,
      conversation_id: input.conversationId ?? null,
    },
    sessionId: session.sessionId,
    headers: { Accept: 'text/event-stream' },
    signal: input.signal,
  })
  if (!response.body) throw new Error('响应没有正文')
  yield* parseSse(response.body)
}
