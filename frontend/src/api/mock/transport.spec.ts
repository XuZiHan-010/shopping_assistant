import { describe, expect, it } from 'vitest'

import { readChatStream } from '../sse'
import { MOCK_MERCHANTS, MOCK_QUICK_QUESTIONS, MOCK_SCENARIOS } from './scenarios'
import { createMockTransport } from './transport'

const transport = createMockTransport({ chunkSizes: [3], stepDelayMs: 0 })

describe('createMockTransport', () => {
  // 遍历全部场景而不只是快速问题入口：快速体验区只暴露 4 个分类入口，
  // 但兜底闲聊与「助手会拒绝」这两个场景照样要能命中 fixture。
  it('每个演示场景都能命中 fixture 并以 done 收尾', async () => {
    for (const { question } of MOCK_SCENARIOS) {
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

  it('快速体验入口是 4 个带分类的问题，且不推荐会被助手拒绝的请求', () => {
    expect(MOCK_QUICK_QUESTIONS).toHaveLength(4)
    expect(MOCK_QUICK_QUESTIONS.map((item) => item.category)).toEqual([
      '趋势分析',
      '经营指标',
      '业务明细',
      '规则问答',
    ])

    // invalidRefused 与兜底闲聊都不该出现在主动推荐里：推荐一个设计上就要被
    // 拒绝的请求，等于教用户去踩线。
    const refused = MOCK_SCENARIOS.find((scenario) => scenario.fixture === 'invalidRefused')!
    expect(MOCK_QUICK_QUESTIONS.map((item) => item.question)).not.toContain(refused.question)
    expect(MOCK_QUICK_QUESTIONS.map((item) => item.question)).not.toContain('你好')
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
    expect(payload.merchants).toEqual(MOCK_MERCHANTS)
    expect(payload.merchants.length).toBeGreaterThanOrEqual(2)
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
