import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'

import { useChatStore } from './chat'

beforeEach(() => {
  setActivePinia(createPinia())
  setChatTransport(createMockTransport({ chunkSizes: [4], stepDelayMs: 0 }))
})

describe('useChatStore', () => {
  it('发送后用户与助手消息各一条，助手落到 complete', async () => {
    const store = useChatStore()

    await store.submitMessage('昨天总 GMV 是多少？')

    expect(store.messages).toHaveLength(2)
    expect(store.messages[0]).toMatchObject({ role: 'user', text: '昨天总 GMV 是多少？' })
    expect(store.messages[1].role).toBe('assistant')
    expect(store.messages[1].status).toBe('complete')
    expect(store.isEmptyConversation).toBe(false)
  })

  it('助手消息累积 step 事件并保存回答', async () => {
    const store = useChatStore()

    await store.submitMessage('昨天总 GMV 是多少？')

    const assistant = store.messages[1]
    expect(assistant.steps.length).toBeGreaterThan(0)
    expect(assistant.answer?.mode).toBe('METRIC')
    expect(assistant.answer?.metric?.displayName).toBeTruthy()
  })

  it('用户消息与助手消息共享同一个 clientRequestId', async () => {
    const store = useChatStore()

    await store.submitMessage('你好')

    expect(store.messages[1].clientRequestId).toBe(store.messages[0].clientRequestId)
    expect(store.messages[0].clientRequestId).not.toHaveLength(0)
  })

  it('空白输入不入列', async () => {
    const store = useChatStore()

    await store.submitMessage('   ')

    expect(store.messages).toHaveLength(0)
  })

  it('reset 清空消息、会话与选中轮次', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')

    store.reset()

    expect(store.messages).toEqual([])
    expect(store.sessionId).toBeUndefined()
    expect(store.selectedRoundId).toBeUndefined()
    expect(store.isEmptyConversation).toBe(true)
  })

  it('选中轮次决定 currentAnswer，不受后续轮次影响', async () => {
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const firstRound = store.messages[1].localId
    await store.submitMessage('我要货品上架，具体规则有吗？')

    expect(store.currentAnswer?.mode).toBe('RULE')
    store.selectRound(firstRound)
    expect(store.currentAnswer?.mode).toBe('METRIC')
  })
})

describe('取消与重试', () => {
  it('取消会中断底层流并置为 cancelled，不是 error', async () => {
    setChatTransport(createMockTransport({ chunkSizes: [1], stepDelayMs: 5 }))
    const store = useChatStore()

    const pending = store.submitMessage('昨天总 GMV 是多少？')
    await new Promise((resolve) => setTimeout(resolve, 10))
    store.cancelMessage(store.messages[1].localId)
    await pending

    expect(store.messages[1].status).toBe('cancelled')
    expect(store.messages[1].errorMessage).toContain('已取消')
  })

  it('重试复用原 clientRequestId', async () => {
    setChatTransport(createMockTransport({ chunkSizes: [1], stepDelayMs: 5 }))
    const store = useChatStore()

    const pending = store.submitMessage('你好')
    await new Promise((resolve) => setTimeout(resolve, 10))
    store.cancelMessage(store.messages[1].localId)
    await pending
    const original = store.messages[1].clientRequestId

    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    await store.retryMessage(store.messages[1].localId)

    expect(store.messages[1].clientRequestId).toBe(original)
    expect(store.messages[1].status).toBe('complete')
    expect(store.messages).toHaveLength(2)
  })

  it('流没有 done 也没有 error 时落到 error，不停在 streaming', async () => {
    setChatTransport(async () => {
      const bytes = new TextEncoder().encode(
        'event: step\ndata: {"label":"正在识别问题","node":"classify"}\n\n',
      )
      return new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(bytes)
            controller.close()
          },
        }),
      )
    })
    const store = useChatStore()

    await store.submitMessage('你好')

    expect(store.messages[1].status).toBe('error')
    expect(store.messages[1].errorMessage).toContain('中断')
  })

  it('重试不累加阶段标签，而是重新开始计数', async () => {
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    const store = useChatStore()
    await store.submitMessage('你好')
    const firstRun = store.messages[1].steps.length

    await store.retryMessage(store.messages[1].localId)

    expect(firstRun).toBeGreaterThan(0)
    // 若 retryMessage 忘了清空 steps，这里会是 firstRun * 2。
    expect(store.messages[1].steps).toHaveLength(firstRun)
  })
})
