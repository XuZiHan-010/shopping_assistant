/**
 * 四个业务端点的调用封装。
 *
 * 组件与 Store 只调这里，不直接碰 transport 或 generated.ts。
 * SSE 的 done 载荷与非流式响应完全一致，所以两条路径共用同一个 Adapter
 * （后端方案 §8.4：只写一套解析逻辑）。
 */
import type { components } from '@/api/generated'
import type { ChatAnswer, ThinkingStep } from '@/types/chat'

import { toChatAnswer } from './adapters/chat'
import { ChatStreamInterruptedError, readChatStream } from './sse'
import { resolveTransport } from './transport'

export interface ConversationSummaryView {
  id: string
  title: string
  createdAt: string
  updatedAt: string
}

export interface DemoMerchantView {
  merchantId: string
  displayName: string
  token: string
}

export interface SubmitChatInput {
  message: string
  sessionId?: string
  clientRequestId: string
}

export interface SubmitChatHandlers {
  onStep(step: ThinkingStep): void
}

/** 流内 error 事件。与 HTTP 层错误分开：后者在 F3 才有码分支。 */
export class ChatStreamError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ChatStreamError'
  }
}

export async function submitChat(
  input: SubmitChatInput,
  handlers: SubmitChatHandlers,
  signal: AbortSignal,
): Promise<ChatAnswer> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: '/api/chat',
      method: 'POST',
      // 只发契约里的字段。merchant_id 由服务端从 Token 解析，前端不传。
      body: {
        message: input.message,
        session_id: input.sessionId ?? null,
        client_request_id: input.clientRequestId,
      },
      accept: 'text/event-stream',
    },
    signal,
  )

  if (!response.body) throw new ChatStreamInterruptedError()

  // done 与 error 互斥由协议保证（readChatStream 不做防御）：这里先到的终止事件
  // 直接决定结果——error 会 throw 并中断循环，done 才会走到下面的赋值。
  let answer: ChatAnswer | undefined
  for await (const event of readChatStream(response.body)) {
    if (event.type === 'step') handlers.onStep(event.step)
    else if (event.type === 'error') throw new ChatStreamError(event.error.message)
    else answer = toChatAnswer(event.raw)
  }

  if (!answer) throw new ChatStreamInterruptedError()
  return answer
}

export async function listConversations(signal: AbortSignal): Promise<ConversationSummaryView[]> {
  const transport = await resolveTransport()
  const response = await transport({ path: '/api/conversations', method: 'GET' }, signal)
  const payload = (await response.json()) as components['schemas']['ConversationListResponse']

  return payload.items.map((item) => ({
    id: item.id,
    title: item.title ?? '未命名会话',
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  }))
}

export interface ConversationDetailView {
  id: string
  title: string
  messages: Array<{ id: string; role: 'user' | 'assistant'; content: string; createdAt: string }>
}

export async function getConversation(
  id: string,
  signal: AbortSignal,
): Promise<ConversationDetailView> {
  const transport = await resolveTransport()
  const response = await transport({ path: `/api/conversations/${id}`, method: 'GET' }, signal)
  const payload = (await response.json()) as components['schemas']['ConversationDetailResponse']

  return {
    id: payload.id,
    title: payload.title ?? '未命名会话',
    messages: payload.messages.map((item) => ({
      id: item.id,
      role: item.role === 'user' ? 'user' : 'assistant',
      content: item.content,
      createdAt: item.created_at,
    })),
  }
}

export async function deleteConversation(id: string, signal: AbortSignal): Promise<void> {
  const transport = await resolveTransport()
  await transport({ path: `/api/conversations/${id}`, method: 'DELETE' }, signal)
}

export async function listDemoMerchants(signal: AbortSignal): Promise<DemoMerchantView[]> {
  const transport = await resolveTransport()
  const response = await transport({ path: '/api/demo/merchants', method: 'GET' }, signal)
  const payload = (await response.json()) as components['schemas']['DemoMerchantListResponse']

  // 注意键名是 merchants；会话列表用的才是 items。
  return payload.merchants.map((item) => ({
    merchantId: item.merchant_id,
    displayName: item.display_name,
    token: item.token,
  }))
}
