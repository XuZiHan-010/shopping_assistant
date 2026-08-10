import { afterEach, describe, expect, it, vi } from 'vitest'

import { listConversations, listDemoMerchants, submitChat } from './chat'
import { createMockTransport } from './mock/transport'
import { setChatTransport, type TransportRequest } from './transport'

/** 构造一段直接封装好的 SSE 响应，绕开 mock 的 fixture 匹配逻辑，模拟任意事件序列。 */
function sseResponseOf(text: string): Response {
  return new Response(new TextEncoder().encode(text), {
    status: 200,
    headers: { 'content-type': 'text/event-stream; charset=utf-8' },
  })
}

setChatTransport(createMockTransport({ chunkSizes: [3], stepDelayMs: 0 }))

afterEach(() => {
  setChatTransport(createMockTransport({ chunkSizes: [3], stepDelayMs: 0 }))
})

describe('submitChat', () => {
  it('推进 step 回调并返回经 Adapter 的领域模型', async () => {
    const onStep = vi.fn()

    const answer = await submitChat(
      { message: '昨天总 GMV 是多少？', clientRequestId: 'c1' },
      { onStep },
      new AbortController().signal,
    )

    expect(onStep).toHaveBeenCalled()
    expect(onStep.mock.calls[0][0]).toHaveProperty('label')
    expect(answer.mode).toBe('METRIC')
    expect(answer.metric?.displayName).toBeTruthy()
    expect(answer.answer).toContain('受控数据查询')
  })

  it('请求体携带 client_request_id 且不含 merchant_id', async () => {
    const seen: unknown[] = []
    setChatTransport(async (request, signal) => {
      seen.push(request.body)
      return createMockTransport({ chunkSizes: [8], stepDelayMs: 0 })(request, signal)
    })

    await submitChat(
      { message: '你好', clientRequestId: 'c2' },
      { onStep: () => {} },
      new AbortController().signal,
    )

    expect(seen[0]).toMatchObject({ message: '你好', client_request_id: 'c2' })
    expect(JSON.stringify(seen[0])).not.toContain('merchant_id')
  })
})

describe('submitChat · 流内错误', () => {
  it('流内 error 事件保留后端错误码，不退化成通用消息', async () => {
    const payload = {
      code: 'LLM_BUDGET_EXCEEDED',
      message: '本月 LLM 预算已用尽',
      request_id: 'req-budget-1',
      retryable: false,
    }
    setChatTransport(async () =>
      sseResponseOf(`event: error\ndata: ${JSON.stringify(payload)}\n\n`),
    )

    await expect(
      submitChat(
        { message: '昨天总 GMV 是多少？', clientRequestId: 'c-err' },
        { onStep: () => {} },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({
      code: 'LLM_BUDGET_EXCEEDED',
      requestId: 'req-budget-1',
    })
  })

  it('流无 done 也无 error 时标记为可重试', async () => {
    setChatTransport(async () => sseResponseOf('event: step\ndata: {"label":"x","node":"y"}\n\n'))

    await expect(
      submitChat(
        { message: '昨天总 GMV 是多少？', clientRequestId: 'c-interrupt' },
        { onStep: () => {} },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ code: 'STREAM_INTERRUPTED', retryable: true })
  })
})

describe('会话与商家端点', () => {
  it('提交后能在会话列表里看到该会话', async () => {
    await submitChat(
      { message: '你好', clientRequestId: 'c3' },
      { onStep: () => {} },
      new AbortController().signal,
    )

    const items = await listConversations(new AbortController().signal)

    expect(items.length).toBeGreaterThanOrEqual(1)
    expect(items[0]).toHaveProperty('createdAt')
  })

  it('演示商家转换为 camelCase 视图模型', async () => {
    const merchants = await listDemoMerchants(new AbortController().signal)

    expect(merchants[0]).toMatchObject({
      merchantId: 'merchant-100',
      displayName: 'Borough商家100',
    })
  })

  it('demo/merchants 不带 Authorization', async () => {
    const seen: TransportRequest[] = []
    setChatTransport(async (request, signal) => {
      seen.push(request)
      return createMockTransport({ chunkSizes: [8], stepDelayMs: 0 })(request, signal)
    })

    await listDemoMerchants(new AbortController().signal)

    expect(seen[0]).toMatchObject({ path: '/api/demo/merchants', auth: 'none' })
  })
})
