import { afterEach, describe, expect, it } from 'vitest'

import type { components } from '@/api/generated'
import { setCredentialProvider } from '../credentials'
import { readChatStream } from '../sse'
import type { ChatTransport } from '../transport'
import { QUICK_QUESTIONS } from '@/constants/quickQuestions'

import { MOCK_MERCHANTS, MOCK_SCENARIOS } from './scenarios'
import { createMockTransport } from './transport'

const transport = createMockTransport({ chunkSizes: [3], stepDelayMs: 0 })

/** 以指定商家 Token 发一轮问答。用完立即清掉 provider，不让身份漏到下一条用例。 */
async function submitVia(target: ChatTransport, token: string, message: string): Promise<void> {
  setCredentialProvider(() => ({ merchantToken: token }))
  try {
    await target(
      {
        path: '/api/chat',
        method: 'POST',
        body: { message, client_request_id: 'isolation-test' },
        accept: 'application/json',
        auth: 'merchant',
      },
      new AbortController().signal,
    )
  } finally {
    setCredentialProvider(undefined)
  }
}

/** 以指定商家 Token 拉会话列表。 */
async function listVia(target: ChatTransport, token: string): Promise<{ items: unknown[] }> {
  setCredentialProvider(() => ({ merchantToken: token }))
  try {
    const response = await target(
      { path: '/api/conversations', method: 'GET', auth: 'merchant' },
      new AbortController().signal,
    )
    return (await response.json()) as { items: unknown[] }
  } finally {
    setCredentialProvider(undefined)
  }
}

describe('createMockTransport', () => {
  afterEach(() => {
    setCredentialProvider(undefined)
  })

  // F3 Task 7：Playwright 强制 VITE_USE_MOCK=true，隔离 e2e 因此必然跑在 Mock
  // 之上；真实后端按 Token 过滤，Mock 若仍是一张全局会话表，隔离 e2e 就是假绿。
  it('同一传输实例下，商家之间的会话互不可见', async () => {
    const isolationTransport = createMockTransport()
    await submitVia(isolationTransport, 'demo-token-100', '昨天的 GMV 是多少')
    const listForB = await listVia(isolationTransport, 'demo-token-101')
    expect(listForB.items).toHaveLength(0)
  })
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
    expect(QUICK_QUESTIONS).toHaveLength(4)
    expect(QUICK_QUESTIONS.map((item) => item.category)).toEqual([
      '趋势分析',
      '经营指标',
      '业务明细',
      '规则问答',
    ])

    // invalidRefused 与兜底闲聊都不该出现在主动推荐里：推荐一个设计上就要被
    // 拒绝的请求，等于教用户去踩线。
    const refused = MOCK_SCENARIOS.find((scenario) => scenario.fixture === 'invalidRefused')!
    expect(QUICK_QUESTIONS.map((item) => item.question)).not.toContain(refused.question)
    expect(QUICK_QUESTIONS.map((item) => item.question)).not.toContain('你好')
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

  it('日报按商家隔离并在同一期内重放同一份结果', async () => {
    const reportTransport = createMockTransport()
    const getReport = async (token: string) => {
      setCredentialProvider(() => ({ merchantToken: token }))
      try {
        const response = await reportTransport(
          { path: '/api/reports/daily', method: 'GET', auth: 'merchant' },
          new AbortController().signal,
        )
        return (await response.json()) as components['schemas']['DailyReportResponse']
      } finally {
        setCredentialProvider(undefined)
      }
    }

    const first = await getReport('demo-token-100')
    const repeated = await getReport('demo-token-100')
    const other = await getReport('demo-token-101')

    expect(first.answer_id).toBe(repeated.answer_id)
    expect(first.answer_id).not.toBe(other.answer_id)
    expect(first.metrics).toHaveLength(6)
    expect(first.suggestions).toHaveLength(2)
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

  it('签名导出路径返回 CSV，不依赖商家 Authorization 头', async () => {
    const response = await transport(
      { path: '/api/exports/export-1?signature=abc', method: 'GET', auth: 'none' },
      new AbortController().signal,
    )

    expect(response.headers.get('content-type')).toContain('text/csv')
    expect(await response.text()).toContain('order_no')
  })
})
