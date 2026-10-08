/**
 * 商家端 v2 会话目录与 v2 Chat 发起（契约 §8.7、§8.9；`n2-conversations-and-feedback` Task 4B）。
 *
 * - 归属由服务端按 `X-Session-Id` 解析，这里只传 `conversation_id`；不存在、别人的、已删除一律 403，
 *   调用方不区分三者；
 * - 历史回答与当轮响应同形，统一经 `toMerchantTurn()`（内部走 `parseFinalResponse`），不另写解析；
 * - 请求带 `Accept-Language`：v2 回答与会话标题按展示语言渲染（R1）。
 */
import { buildLocaleHeaders } from '@/api/credentials'
import type { components } from '@/api/generated'

import type { ChartSeries } from '@/types/chat'

import { parseFinalResponse, type ChatTurnEnvelope } from '../chatTurnEnvelope'
import { ChatStreamInterruptedError } from '../sse'
import {
  readMerchantChatStream,
  toToolCallView,
  type MerchantChatStreamEvent,
  type ToolCallView,
} from './chatV2'
import type { Page } from './merchantOps'
import { merchantRequest, queryString } from './v2Http'

type RawMerchantChatResponse = components['schemas']['MerchantChatResponse']
type RawVisualization = components['schemas']['Visualization']
type RawSummary = components['schemas']['MerchantConversationSummary']
type RawMessage = components['schemas']['MerchantConversationMessage']
type RawSummaryPage = components['schemas']['CursorPage_MerchantConversationSummary_']
type RawDetail = components['schemas']['MerchantConversationDetailResponse']
type RawFeedbackRequest = components['schemas']['V2FeedbackRequest']
type RawFeedbackResponse = components['schemas']['V2FeedbackResponse']

/** 一次打开对话最多翻的消息页数；超出部分不渲染并如实提示。 */
const MAX_MESSAGE_PAGES = 10
const MESSAGE_PAGE_SIZE = 100
export const MAX_HISTORY_MESSAGES = MAX_MESSAGE_PAGES * MESSAGE_PAGE_SIZE

export interface MerchantConversationSummary {
  id: string
  title: string
  createdAt: string
  updatedAt: string
}

export interface MerchantTurn {
  id: string
  conversationId: string
  envelope: ChatTurnEnvelope
  toolCalls: ToolCallView[]
  suggestions: string[]
  chart: ChartSeries
}

/** 字段原样映射为驼峰键——形状与 v1 `ChartSeries` 一致，供 `MetricChartPanel.vue` 直接消费。
 *
 * 后端契约给这个字段默认值 `{enabled: false}`，但历史回答（本字段上线前落盘的）
 * 或测试替身数据可能整个字段都缺失——同样归一为「无图表」，不抛错。 */
function toChartSeries(raw: RawVisualization | undefined): ChartSeries {
  if (!raw) return { enabled: false, allowedTypes: [], data: [] }
  return {
    enabled: raw.enabled,
    type: raw.type ?? undefined,
    allowedTypes: raw.allowed_types ?? [],
    title: raw.title ?? undefined,
    dimensionKey: raw.dimension_key ?? undefined,
    metricKey: raw.metric_key ?? undefined,
    unit: raw.unit ?? undefined,
    data: raw.data ?? [],
  }
}

export interface MerchantConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  /** 助手消息的完整最终响应；提问消息为 `null`。 */
  turn: MerchantTurn | null
  feedback: MerchantFeedbackState | null
}

export interface MerchantConversationHistory {
  messages: MerchantConversationMessage[]
  /** 超过翻页上限仍有后续消息时为 true。 */
  truncated: boolean
}

export interface MerchantFeedbackState {
  adopted: boolean
  reaction: RawFeedbackResponse['reaction']
  reason: string | null
}

export type MerchantFeedbackIntent =
  | { kind: 'ADOPTION'; adopted: boolean }
  | { kind: 'REACTION'; reaction: RawFeedbackResponse['reaction']; reason?: string }

export type MerchantFeedbackInput = MerchantFeedbackIntent & { clientRequestId: string }

/** v2 反馈一次只修改一种语义；只从服务端完整回执取得最终状态。 */
export async function submitMerchantFeedback(
  sessionId: string,
  answerId: string,
  input: MerchantFeedbackInput,
): Promise<MerchantFeedbackState> {
  const payload: RawFeedbackRequest =
    input.kind === 'ADOPTION'
      ? { client_request_id: input.clientRequestId, kind: input.kind, adopted: input.adopted }
      : {
          client_request_id: input.clientRequestId,
          kind: input.kind,
          reaction: input.reaction,
          ...(input.reason ? { reason: input.reason } : {}),
        }
  const response = await merchantRequest(
    `/api/v2/merchant/answers/${encodeURIComponent(answerId)}/feedback`,
    sessionId,
    {
      method: 'POST',
      headers: { ...buildLocaleHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  const raw = (await response.json()) as RawFeedbackResponse
  return { adopted: raw.adopted, reaction: raw.reaction, reason: raw.reason }
}

export function toMerchantTurn(raw: RawMerchantChatResponse): MerchantTurn {
  return {
    id: raw.id,
    conversationId: raw.conversation_id,
    envelope: parseFinalResponse(raw),
    toolCalls: raw.tool_calls.map(toToolCallView),
    suggestions: raw.suggestions ?? [],
    chart: toChartSeries(raw.visualization),
  }
}

function toSummary(raw: RawSummary): MerchantConversationSummary {
  return { id: raw.id, title: raw.title, createdAt: raw.created_at, updatedAt: raw.updated_at }
}

function toMessage(raw: RawMessage): MerchantConversationMessage {
  return {
    id: raw.id,
    role: raw.role,
    content: raw.content,
    createdAt: raw.created_at,
    turn: raw.answer ? toMerchantTurn(raw.answer) : null,
    feedback: raw.feedback,
  }
}

function conversationPath(conversationId: string): string {
  return `/api/v2/merchant/conversations/${encodeURIComponent(conversationId)}`
}

/** 最近活动在前（`updated_at DESC, id DESC`，契约 §8.9.2）。 */
export async function fetchMerchantConversations(
  sessionId: string,
  cursor: string | null = null,
): Promise<Page<MerchantConversationSummary>> {
  const response = await merchantRequest(
    `/api/v2/merchant/conversations${queryString({ cursor, limit: 20 })}`,
    sessionId,
    { headers: buildLocaleHeaders() },
  )
  const page = (await response.json()) as RawSummaryPage
  return { items: page.items.map(toSummary), nextCursor: page.next_cursor, hasMore: page.has_more }
}

/** 消息 `created_at ASC`；逐页取完（有上限）。 */
export async function fetchMerchantConversationHistory(
  sessionId: string,
  conversationId: string,
): Promise<MerchantConversationHistory> {
  const messages: MerchantConversationMessage[] = []
  let cursor: string | null = null
  for (let index = 0; index < MAX_MESSAGE_PAGES; index += 1) {
    const response = await merchantRequest(
      `${conversationPath(conversationId)}${queryString({ cursor, limit: MESSAGE_PAGE_SIZE })}`,
      sessionId,
      { headers: buildLocaleHeaders() },
    )
    const detail = (await response.json()) as RawDetail
    messages.push(...detail.messages.items.map(toMessage))
    if (!detail.messages.has_more || !detail.messages.next_cursor) {
      return { messages, truncated: false }
    }
    cursor = detail.messages.next_cursor
  }
  return { messages, truncated: true }
}

export async function deleteMerchantConversation(
  sessionId: string,
  conversationId: string,
): Promise<void> {
  await merchantRequest(conversationPath(conversationId), sessionId, { method: 'DELETE' })
}

export interface MerchantChatInput {
  clientRequestId: string
  message: string
  conversationId: string | null
}

/** 发起一轮 v2 商家对话；流以 `turn_complete` 或 `error` 收尾。只发契约字段，身份由会话头解析。 */
export async function* streamMerchantChat(
  sessionId: string,
  input: MerchantChatInput,
  signal?: AbortSignal,
): AsyncGenerator<MerchantChatStreamEvent> {
  const response = await merchantRequest('/api/v2/merchant/chat', sessionId, {
    method: 'POST',
    headers: {
      ...buildLocaleHeaders(),
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      client_request_id: input.clientRequestId,
      message: input.message,
      conversation_id: input.conversationId,
    }),
    signal,
  })
  if (!response.body) throw new ChatStreamInterruptedError()
  yield* readMerchantChatStream(response.body)
}
