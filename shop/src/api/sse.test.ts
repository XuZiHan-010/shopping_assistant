import { describe, expect, it } from 'vitest'
import { ApiError } from './errors'
import { ChatStreamInterruptedError, parseSse, type ChatStreamEvent } from './sse'

const encode = (text: string) => new TextEncoder().encode(text)

function streamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  })
}

function splitAt(bytes: Uint8Array, points: number[]): Uint8Array[] {
  const cuts = [0, ...points, bytes.length]
  return cuts.slice(0, -1).map((start, index) => bytes.slice(start, cuts[index + 1]))
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<ChatStreamEvent[]> {
  const events: ChatStreamEvent[] = []
  for await (const event of parseSse(stream)) events.push(event)
  return events
}

const completion = (answer: string) =>
  JSON.stringify({
    id: 'a1', conversation_id: 'c1', answer, tool_calls: [], created_at: '2026-09-01T00:00:00Z',
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    quality_status: 'PASSED', quality_attempts: 1, degraded: false, degraded_reason: null,
    answer_mode: 'SHOP_GUIDE',
  })

describe('v2 SSE 解析', () => {
  it('在 UTF-8 多字节字符中间被切开时仍能正确解析', async () => {
    const bytes = encode(`event: turn_complete\ndata: ${completion('本店有 2 款')}\n\n`)
    const zh = bytes.indexOf(0xe6) // 「本」的首字节
    const chunks = splitAt(bytes, [zh + 1, zh + 5, bytes.length - 3])
    const events = await collect(streamOf(chunks))
    const last = events.at(-1)
    expect(last?.type).toBe('turn_complete')
    expect(last?.type === 'turn_complete' && last.response.answer).toBe('本店有 2 款')
  })

  it('一次读取含多个事件，一个事件分多次读取，都能还原', async () => {
    const text =
      'event: tool_call\ndata: {"tool_name":"search_products","call_id":"c1","status":"STARTED","summary":"正在处理"}\n\n' +
      'event: tool_result\ndata: {"tool_name":"search_products","call_id":"c1","status":"SUCCEEDED","summary":"处理完成"}\n\n' +
      `event: turn_complete\ndata: ${completion('好')}\n\n`
    const bytes = encode(text)
    const together = await collect(streamOf([bytes]))
    const dripped = await collect(streamOf(splitAt(bytes, Array.from({ length: 40 }, (_, i) => (i + 1) * 7))))
    expect(together.map((e) => e.type)).toEqual(['tool_call', 'tool_result', 'turn_complete'])
    expect(dripped.map((e) => e.type)).toEqual(['tool_call', 'tool_result', 'turn_complete'])
  })

  it('工具事件只暴露工具名、状态与摘要，不带参数或结果', async () => {
    const wire =
      'event: tool_call\ndata: {"tool_name":"set_cart_item","call_id":"c9","status":"STARTED","summary":"正在处理","arguments":{"product_id":"secret"},"result":{"rows":[1]}}\n\n' +
      `event: turn_complete\ndata: ${completion('好')}\n\n`
    const [first] = await collect(streamOf([encode(wire)]))
    expect(first).toEqual({
      type: 'tool_call',
      call: { toolName: 'set_cart_item', callId: 'c9', status: 'STARTED', summary: '正在处理' },
    })
  })

  it('注释心跳被忽略', async () => {
    const events = await collect(streamOf([encode(`: keep-alive\n\nevent: turn_complete\ndata: ${completion('好')}\n\n`)]))
    expect(events.map((e) => e.type)).toEqual(['turn_complete'])
  })

  it('error 事件携带统一错误结构并终止流', async () => {
    const body = JSON.stringify({ code: 'RATE_LIMITED', message: '请求过于频繁', request_id: 'r1', details: [], retryable: true })
    const events = await collect(streamOf([encode(`event: error\ndata: ${body}\n\n`)]))
    const error = events.at(-1)
    expect(error?.type).toBe('error')
    expect(error?.type === 'error' && error.error).toBeInstanceOf(ApiError)
    expect(error?.type === 'error' && error.error.code).toBe('RATE_LIMITED')
  })

  it('流结束时既没有 turn_complete 也没有 error：抛中断错误，不永远 streaming', async () => {
    const stream = streamOf([encode('event: tool_call\ndata: {"tool_name":"x","call_id":"1","status":"STARTED","summary":"正在处理"}\n\n')])
    await expect(collect(stream)).rejects.toBeInstanceOf(ChatStreamInterruptedError)
  })
})
