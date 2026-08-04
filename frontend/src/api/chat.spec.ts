import { afterEach, describe, expect, it, vi } from 'vitest'

import { listConversations, listDemoMerchants, submitChat } from './chat'
import { createMockTransport } from './mock/transport'
import { setChatTransport } from './transport'

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
    expect(answer.answer).toContain('B4')
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
})
