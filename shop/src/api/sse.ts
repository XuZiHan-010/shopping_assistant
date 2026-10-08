/**
 * v2 顾客 Chat 的 SSE 增量解析。
 *
 * 不能用原生 EventSource：聊天请求需要 POST、JSON 请求体与 `X-Session-Id` 头。
 * 服务端不做分块对齐承诺（契约 §8.4），必须按字节流累积——一次 read() 可能是半个事件、
 * 多个事件，也可能把一个中文字切成两半（所以解码用 `stream: true`）。
 */
import type { ChatTurn, ToolCall } from '@/types/chat'
import { toChatTurn, toToolCall } from './adapters/chat'
import { ApiError } from './errors'
import type { components } from './generated'

export type ChatStreamEvent =
  | { type: 'tool_call'; call: ToolCall }
  | { type: 'tool_result'; call: ToolCall }
  | { type: 'turn_complete'; response: ChatTurn }
  | { type: 'error'; error: ApiError }

/** 流既没有 turn_complete 也没有 error 就结束了：不能让界面永久停在「回答中」。 */
export class ChatStreamInterruptedError extends Error {
  readonly retryable = true
  constructor() {
    super('ChatStreamInterruptedError')
    this.name = 'ChatStreamInterruptedError'
  }
}

interface Frame {
  event: string
  data: string
}

function parseFrame(raw: string): Frame | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith(':')) continue // 心跳注释
    if (line.startsWith('event:')) event = line.slice('event:'.length).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trim())
  }
  return dataLines.length === 0 ? null : { event, data: dataLines.join('\n') }
}

// 事件类型只来自 `event:` 行，不从 data 里再读一个 type 键。
function toEvent(frame: Frame): ChatStreamEvent | null {
  const payload: unknown = JSON.parse(frame.data)
  switch (frame.event) {
    case 'tool_call':
      return { type: 'tool_call', call: toToolCall(payload as components['schemas']['ToolCallDisplay']) }
    case 'tool_result':
      return { type: 'tool_result', call: toToolCall(payload as components['schemas']['ToolCallDisplay']) }
    case 'turn_complete':
      return { type: 'turn_complete', response: toChatTurn(payload as components['schemas']['ShopChatResponse']) }
    case 'error':
      return { type: 'error', error: new ApiError(0, payload as components['schemas']['ErrorResponse']) }
    default:
      return null
  }
}

export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatStreamEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let terminated = false

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      for (;;) {
        const index = buffer.indexOf('\n\n')
        if (index === -1) break
        const raw = buffer.slice(0, index)
        buffer = buffer.slice(index + 2)
        const frame = parseFrame(raw)
        const event = frame ? toEvent(frame) : null
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
