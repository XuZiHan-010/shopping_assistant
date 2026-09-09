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
import type { SupportedLocale } from '@/i18n'
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

/**
 * 响应语言与当前展示语言不一致时抛出的契约错误。
 *
 * 二次防线：语言切换时 Store 会主动 `AbortController.abort()` 掉旧流
 * （Task 11 Step 6），正常情况下过期请求根本走不到这里；但 abort 信号和
 * 网络response 到达终究是两条异步链路，理论上仍可能出现「abort 还没生效，
 * 响应已经在路上」的极窄竞态窗口。后端在**每个**响应上都会回显
 * `Content-Language`（`backend/app/main.py` 的请求中间件），与请求发出时刻
 * 的 `Accept-Language` 一一对应；比较它与「此刻」的展示语言，能在 abort
 * 没来得及生效时兜住这最后一步，而不是把上一语言的回答悄悄塞进当前界面。
 */
export class ResponseLocaleMismatchError extends AppError {
  constructor(actual: string, expected: SupportedLocale) {
    super('CONTRACT', `响应语言（${actual}）与当前展示语言（${expected}）不一致，已丢弃过期响应。`, {
      shouldReport: true,
    })
    this.name = 'ResponseLocaleMismatchError'
  }
}

/**
 * 校验响应的 `Content-Language` 头与调用方此刻期望的展示语言是否一致。
 *
 * 后端在缺少该头时也可能不设置（如反向代理直接拦下的 5xx 页面）——此时不做
 * 判断，交给既有的错误处理路径，不在这里编造一个「语言不一致」的假象。
 */
export function assertResponseLocale(response: Response, expected: SupportedLocale): void {
  const actual = response.headers.get('Content-Language')
  if (actual && actual !== expected) {
    throw new ResponseLocaleMismatchError(actual, expected)
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
