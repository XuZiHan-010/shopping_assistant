import { describe, expect, it } from 'vitest'

import { readChatStream } from '../sse'
import { MOCK_MERCHANTS, MOCK_QUICK_QUESTIONS } from './scenarios'
import { createMockTransport } from './transport'

const transport = createMockTransport({ chunkSizes: [3], stepDelayMs: 0 })

describe('createMockTransport', () => {
  it('每个快速问题都能命中 fixture 并以 done 收尾', async () => {
    for (const question of MOCK_QUICK_QUESTIONS) {
      const response = await transport(
        {
          path: '/api/chat',
          method: 'POST',
          body: { message: question, client_request_id: 'c1' },
          accept: 'text/event-stream',
        },
        new AbortController().signal,
      )

      const events = []
      for await (const event of readChatStream(response.body!)) events.push(event)

      expect(events.at(-1)?.type, question).toBe('done')
      expect(events.some((e) => e.type === 'step')).toBe(true)
    }
  })

  it('Accept: application/json 时返回普通 JSON，不走流', async () => {
    const response = await transport(
      {
        path: '/api/chat',
        method: 'POST',
        body: { message: '你好', client_request_id: 'c2' },
        accept: 'application/json',
      },
      new AbortController().signal,
    )

    const payload = await response.json()
    expect(payload.answer_mode).toBe('CHAT')
  })

  it('返回演示商家列表，且不含 merchant_id 以外的身份泄漏', async () => {
    const response = await transport(
      { path: '/api/demo/merchants', method: 'GET' },
      new AbortController().signal,
    )

    const payload = await response.json()
    expect(payload.items).toEqual(MOCK_MERCHANTS)
    expect(payload.items.length).toBeGreaterThanOrEqual(2)
  })

  it('已中止的 signal 会让请求以 AbortError 拒绝', async () => {
    const controller = new AbortController()
    controller.abort()

    await expect(
      transport(
        {
          path: '/api/chat',
          method: 'POST',
          body: { message: '你好', client_request_id: 'c3' },
          accept: 'text/event-stream',
        },
        controller.signal,
      ),
    ).rejects.toMatchObject({ name: 'AbortError' })
  })
})
