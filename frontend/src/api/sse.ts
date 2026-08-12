/**
 * SSE 增量解析。
 *
 * 不能用原生 EventSource：聊天请求同时需要 POST、JSON 请求体和 Authorization 头，
 * 三者 EventSource 都不支持（前端方案 §6.1）。
 *
 * 服务端不做分块对齐承诺（后端方案 §8.4），所以必须按字节流累积：一次 read()
 * 可能是半个事件，也可能是多个事件，还可能把一个中文字切成两半。
 */
import type { components } from '@/api/generated'
import type { ThinkingStep } from '@/types/chat'

import { AppError } from './errors'

type RawChatResponse = components['schemas']['ChatResponse']
type RawErrorResponse = components['schemas']['ErrorResponse']

export interface SseFrame {
  event: string
  data: string
}

export type ChatStreamEvent =
  | { type: 'step'; step: ThinkingStep }
  | { type: 'done'; raw: RawChatResponse }
  | { type: 'error'; error: RawErrorResponse }

/**
 * 流既没有 done 也没有 error 就结束了。消息必须落到 error，不能永久 streaming。
 * 是 `AppError` 的 `STREAM_INTERRUPTED` 特化，值得让用户重试。
 */
export class ChatStreamInterruptedError extends AppError {
  constructor() {
    super('STREAM_INTERRUPTED', '回答流意外中断，请重试。', { retryable: true })
    this.name = 'ChatStreamInterruptedError'
  }
}

export class SseFrameBuffer {
  private buffer = ''

  push(text: string): SseFrame[] {
    this.buffer += text
    const frames: SseFrame[] = []

    for (;;) {
      const index = this.buffer.indexOf('\n\n')
      if (index === -1) break

      const raw = this.buffer.slice(0, index)
      this.buffer = this.buffer.slice(index + 2)
      const frame = parseFrame(raw)
      if (frame) frames.push(frame)
    }

    return frames
  }
}

function parseFrame(raw: string): SseFrame | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of raw.split('\n')) {
    // 以冒号开头的是注释（心跳 `: keep-alive`），不是业务事件。
    if (line.startsWith(':')) continue
    if (line.startsWith('event:')) event = line.slice('event:'.length).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trim())
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

// 事件类型只来自 event: 行，不从 data JSON 里再读一个 type 键（后端方案 §8.4）。
function toStreamEvent(frame: SseFrame): ChatStreamEvent | null {
  if (frame.event === 'step') return { type: 'step', step: JSON.parse(frame.data) }
  if (frame.event === 'done') return { type: 'done', raw: JSON.parse(frame.data) }
  if (frame.event === 'error') return { type: 'error', error: JSON.parse(frame.data) }
  return null
}

export async function* readChatStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<ChatStreamEvent> {
  const reader = body.getReader()
  // stream: true 是必须的——按块单独解码会让中文在块边界变成乱码。
  const decoder = new TextDecoder('utf-8')
  const frames = new SseFrameBuffer()
  let terminated = false

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      for (const frame of frames.push(decoder.decode(value, { stream: true }))) {
        const event = toStreamEvent(frame)
        if (!event) continue
        if (event.type === 'done' || event.type === 'error') terminated = true
        yield event
      }
    }
  } finally {
    reader.releaseLock()
  }

  if (!terminated) throw new ChatStreamInterruptedError()
}
