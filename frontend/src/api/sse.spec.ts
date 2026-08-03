import { describe, expect, it } from 'vitest'

import { CHAT_FIXTURES } from './mock/fixtures.generated'
import { ChatStreamInterruptedError, SseFrameBuffer, readChatStream } from './sse'

function streamOf(bytes: Uint8Array, sizes: number[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      let offset = 0
      let index = 0
      while (offset < bytes.length) {
        const size = sizes[index % sizes.length]
        controller.enqueue(bytes.slice(offset, offset + size))
        offset += size
        index += 1
      }
      controller.close()
    },
  })
}

function encodeStream(fixture: (typeof CHAT_FIXTURES)['metricGmv']): Uint8Array {
  let text = ''
  for (const step of fixture.thinking_steps ?? []) {
    text += `event: step\ndata: ${JSON.stringify(step)}\n\n`
  }
  text += ': keep-alive\n\n'
  text += `event: done\ndata: ${JSON.stringify(fixture)}\n\n`
  return new TextEncoder().encode(text)
}

describe('SseFrameBuffer', () => {
  it('按空行切分，丢弃注释心跳', () => {
    const buffer = new SseFrameBuffer()

    expect(buffer.push(': keep-alive\n\n')).toEqual([])
    expect(buffer.push('event: step\ndata: {"a":1}\n\n')).toEqual([
      { event: 'step', data: '{"a":1}' },
    ])
  })

  it('一次 push 含多个事件时全部吐出', () => {
    const buffer = new SseFrameBuffer()

    const frames = buffer.push('event: step\ndata: 1\n\nevent: done\ndata: 2\n\n')

    expect(frames).toEqual([
      { event: 'step', data: '1' },
      { event: 'done', data: '2' },
    ])
  })

  it('事件被切成两半时先不吐，凑齐再吐', () => {
    const buffer = new SseFrameBuffer()

    expect(buffer.push('event: step\ndata: {"lab')).toEqual([])
    expect(buffer.push('el":"x"}\n\n')).toEqual([{ event: 'step', data: '{"label":"x"}' }])
  })
})

describe('readChatStream', () => {
  // 1 和 3 字节的块必然切断 UTF-8 中文（3 字节/字）和事件边界。
  it.each([[1], [3], [7], [64]])('按 %i 字节切块仍能还原中文与完整载荷', async (size) => {
    const fixture = CHAT_FIXTURES.metricGmv
    const events = []
    for await (const event of readChatStream(streamOf(encodeStream(fixture), [size]))) {
      events.push(event)
    }

    const steps = events.filter((e) => e.type === 'step')
    expect(steps).toHaveLength(fixture.thinking_steps.length)
    expect(steps[0]).toEqual({ type: 'step', step: fixture.thinking_steps[0] })

    const last = events.at(-1)
    expect(last?.type).toBe('done')
    expect(last?.type === 'done' && last.raw.answer).toBe(fixture.answer)
    expect(last?.type === 'done' && last.raw.answer).toContain('昨天总 GMV')
  })

  it('流结束却没有 done 或 error 时抛中断错误', async () => {
    const bytes = new TextEncoder().encode('event: step\ndata: {"label":"x","node":"y"}\n\n')

    await expect(async () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 只关心迭代结束时的行为，不关心产出的事件本身
      for await (const _ of readChatStream(streamOf(bytes, [5]))) {
        // 只关心迭代结束时的行为
      }
    }).rejects.toThrow(ChatStreamInterruptedError)
  })

  it('error 事件作为终止事件产出，不抛中断错误', async () => {
    const payload = { code: 'INTERNAL_ERROR', message: '演示失败', request_id: 'r1' }
    const bytes = new TextEncoder().encode(`event: error\ndata: ${JSON.stringify(payload)}\n\n`)

    const events = []
    for await (const event of readChatStream(streamOf(bytes, [4]))) {
      events.push(event)
    }

    expect(events).toEqual([{ type: 'error', error: payload }])
  })
})
