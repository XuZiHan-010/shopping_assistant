/**
 * v2 商家 Chat 的 SSE 事件解析（`n2-merchant-vue-v2-migration` Task 6）。
 *
 * v2 事件集（契约 §8.7.5）：`step` / `tool_call` / `tool_result` / `turn_complete` / `error`。
 * - `step`、`error` 与 v1 同名同构，直通；
 * - **`turn_complete` 取代 v1 的 `done`**：两者都在 `chatTurnEnvelope.ts` 的
 *   `parseFinalResponse` 汇合，前端只保留一处最终响应解析；
 * - `tool_call` 与 `tool_result` **形状不同**：`tool_result` 没有 `tool_name`，多了
 *   `duration_ms` / `row_count`，要按 `call_id` 与对应的 `tool_call` 对上。两者都只
 *   携带受控状态与固定短句，不携带参数或结果正文。
 *
 * `tool_result` 的载荷只出现在 SSE 里、不在任何 JSON 响应模型中，所以 OpenAPI
 * 组件（进而 `generated.ts`）里没有它的类型；这里按 §8.7.5 手写，**不改 generated.ts**。
 *
 * 字节缓冲复用 `SseFrameBuffer`（`api/sse.ts`）——服务端同样不做分块对齐承诺。
 */
import type { components } from '@/api/generated'
import type { ThinkingStep } from '@/types/chat'

import { parseFinalResponse, type ChatTurnEnvelope } from '../chatTurnEnvelope'
import { ChatStreamInterruptedError, SseFrameBuffer, type SseFrame } from '../sse'

type RawMerchantChatResponse = components['schemas']['MerchantChatResponse']
type RawErrorResponse = components['schemas']['ErrorResponse']
type RawToolCallDisplay = components['schemas']['ToolCallDisplay']
type ToolDisplayStatus = components['schemas']['ToolDisplayStatus']
type PublicToolSummary = RawToolCallDisplay['summary']

/** 契约 §8.7.5 `ToolResultDisplay`。 */
interface RawToolResultDisplay {
  call_id: string
  status: ToolDisplayStatus
  duration_ms: number
  row_count: number | null
  summary: PublicToolSummary
}

export interface ToolCallView {
  toolName: string
  callId: string
  status: ToolDisplayStatus
  summary: PublicToolSummary
}

export interface ToolResultView {
  callId: string
  status: ToolDisplayStatus
  durationMs: number
  /** `null` 表示「行数不适用」，不要显示成 0 行。 */
  rowCount: number | null
  summary: PublicToolSummary
}

export type MerchantChatStreamEvent =
  | { type: 'step'; step: ThinkingStep }
  | { type: 'tool_call'; call: ToolCallView }
  | { type: 'tool_result'; result: ToolResultView }
  | { type: 'turn_complete'; raw: RawMerchantChatResponse; envelope: ChatTurnEnvelope }
  | { type: 'error'; error: RawErrorResponse }

export function toToolCallView(raw: RawToolCallDisplay): ToolCallView {
  return { toolName: raw.tool_name, callId: raw.call_id, status: raw.status, summary: raw.summary }
}

function toToolResultView(raw: RawToolResultDisplay): ToolResultView {
  return {
    callId: raw.call_id,
    status: raw.status,
    durationMs: raw.duration_ms,
    rowCount: raw.row_count,
    summary: raw.summary,
  }
}

// 事件类型只来自 event: 行，与 v1 同一纪律（后端方案 §8.4/§8.7.5）。
function toMerchantStreamEvent(frame: SseFrame): MerchantChatStreamEvent | null {
  if (frame.event === 'step') return { type: 'step', step: JSON.parse(frame.data) }
  if (frame.event === 'tool_call') {
    return { type: 'tool_call', call: toToolCallView(JSON.parse(frame.data)) }
  }
  if (frame.event === 'tool_result') {
    return { type: 'tool_result', result: toToolResultView(JSON.parse(frame.data)) }
  }
  if (frame.event === 'turn_complete') {
    const raw = JSON.parse(frame.data) as RawMerchantChatResponse
    return { type: 'turn_complete', raw, envelope: parseFinalResponse(raw) }
  }
  if (frame.event === 'error') return { type: 'error', error: JSON.parse(frame.data) }
  return null
}

export async function* readMerchantChatStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<MerchantChatStreamEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8')
  const frames = new SseFrameBuffer()
  let terminated = false

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      for (const frame of frames.push(decoder.decode(value, { stream: true }))) {
        const event = toMerchantStreamEvent(frame)
        if (!event) continue
        if (event.type === 'turn_complete' || event.type === 'error') terminated = true
        yield event
      }
    }
  } finally {
    reader.releaseLock()
  }

  if (!terminated) throw new ChatStreamInterruptedError()
}
