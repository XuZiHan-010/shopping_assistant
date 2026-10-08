/**
 * 聊天域业务端点的调用封装。
 *
 * 组件与 Store 只调这里，不直接碰 transport 或 generated.ts。
 * SSE 的 done 载荷与非流式响应完全一致，所以两条路径共用同一个 Adapter
 * （后端方案 §8.4：只写一套解析逻辑）。
 */
import type { components } from '@/api/generated'
import { resolveRequestLocale } from '@/api/credentials'
import type { ChatAnswer, FeedbackState, ThinkingStep } from '@/types/chat'

import { toChatAnswer, toFeedbackRequestPayload, toFeedbackState } from './adapters/chat'
import { AppError } from './errors'
import { assertResponseLocale, ChatStreamInterruptedError, readChatStream } from './sse'
import { resolveTransport } from './transport'

export interface ConversationSummaryView {
  id: string
  title: string
  createdAt: string
  updatedAt: string
}

export interface ConversationListView {
  items: ConversationSummaryView[]
  /**
   * 本页任意一条会话标题未能在预算内翻译完成时为 true（后端
   * `ConversationListResponse.localization_degraded`，Task 7 §8.6.3）。
   * 未降级时固定 false，与 R7 的显式降级要求一致。
   */
  localizationDegraded: boolean
  localizationDegradedReason?: string
}

export interface DemoMerchantView {
  merchantId: string
  displayName: string
  /**
   * 可选是因为 `authStore.invalidate()`（前端方案 F3 Task 6）在 401 时会把内存里
   * 这份 Token 抹掉，但仍保留同一个商家对象（displayName/merchantId 不变）——
   * 让切换器能继续显示「当前商家是谁」，只是它已经没有可用凭证。
   */
  token?: string
}

export interface SubmitChatInput {
  message: string
  sessionId?: string
  clientRequestId: string
}

export interface SubmitChatHandlers {
  onStep(step: ThinkingStep): void
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
      auth: 'merchant',
    },
    signal,
  )

  if (!response.body) throw new ChatStreamInterruptedError()

  // 二次防线：本轮请求发出之后、响应回来之前，若展示语言已经切换（Task 11
  // Step 6 的 epoch 机制通常已经 abort 了这次请求），这里用响应自带的
  // `Content-Language` 再确认一次，防止极窄的竞态窗口把上一语言的回答
  // 悄悄塞进当前界面（见 `sse.ts` 的 `assertResponseLocale`）。
  assertResponseLocale(response, resolveRequestLocale())

  // done 与 error 互斥由协议保证（readChatStream 不做防御）：这里先到的终止事件
  // 直接决定结果——error 会 throw 并中断循环，done 才会走到下面的赋值。
  // 用 AppError.fromErrorResponse 而不是丢消息的通用 Error：保留后端的 code
  // （如 LLM_BUDGET_EXCEEDED）与 request_id，UI 才能把它和普通 5xx 区分开。
  let answer: ChatAnswer | undefined
  for await (const event of readChatStream(response.body)) {
    if (event.type === 'step') handlers.onStep(event.step)
    else if (event.type === 'error') throw AppError.fromErrorResponse(event.error)
    else answer = toChatAnswer(event.raw)
  }

  if (!answer) throw new ChatStreamInterruptedError()
  return answer
}

/** 不造分页：固定拉最近 `limit` 个会话，UI 在列表底部提示「仅显示最近 N 个」（路线图 A8-6）。 */
export async function listConversations(
  signal: AbortSignal,
  limit = 50,
): Promise<ConversationListView> {
  const transport = await resolveTransport()
  const response = await transport(
    { path: `/api/conversations?limit=${limit}`, method: 'GET', auth: 'merchant' },
    signal,
  )
  const payload = (await response.json()) as components['schemas']['ConversationListResponse']

  return {
    items: payload.items.map((item) => ({
      id: item.id,
      title: item.title ?? '未命名会话',
      createdAt: item.created_at,
      updatedAt: item.updated_at,
    })),
    localizationDegraded: payload.localization_degraded ?? false,
    localizationDegradedReason: payload.localization_degraded_reason ?? undefined,
  }
}


export async function submitFeedback(
  answerId: string,
  state: FeedbackState,
  signal: AbortSignal,
): Promise<FeedbackState> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/answers/${answerId}/feedback`,
      method: 'POST',
      auth: 'merchant',
      body: toFeedbackRequestPayload(state),
    },
    signal,
  )
  return toFeedbackState((await response.json()) as components['schemas']['FeedbackResponse'])
}

/** 演示商家列表是公开接口，不带 Authorization——鸡生蛋问题：选商家之前哪来商家凭证。 */
export async function listDemoMerchants(signal: AbortSignal): Promise<DemoMerchantView[]> {
  const transport = await resolveTransport()
  const response = await transport(
    { path: '/api/demo/merchants', method: 'GET', auth: 'none' },
    signal,
  )
  const payload = (await response.json()) as components['schemas']['DemoMerchantListResponse']

  // 注意键名是 merchants；会话列表用的才是 items。
  return payload.merchants.map((item) => ({
    merchantId: item.merchant_id,
    displayName: item.display_name,
    token: item.token,
  }))
}
