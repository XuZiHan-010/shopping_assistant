import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { AppError } from '@/api/errors'
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
    // 回归防线：Task 1 把一切错误统一包成 AppError 后，原先
    // `(error as Error).name === 'AbortError'` 的判断会静默失效——`name` 恒为
    // `'AppError'`。必须按 `error.code === 'CANCELLED'` 分支，不是字符串/name
    // 比对，否则用户每次点「停止」都会看到「出错了」。
    expect(store.messages[1].error?.code).toBe('CANCELLED')
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
    expect(store.messages[1].error?.code).toBe('STREAM_INTERRUPTED')
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

  it('第一轮仍在进行时调用 retryMessage 不会启动第二轮，取消依然生效', async () => {
    // 复现审查发现的问题：如果 retryMessage 在第一轮还没结束时又跑一次 runRound，
    // 会用同一个 assistant.localId 覆盖 controllers 里的 AbortController；第一轮
    // 结束时的 finally 再把它 delete 掉，之后 cancelMessage 就静默失效——用户以为
    // 取消了，请求其实还在跑、还在计费。这里断言：进行中调用 retryMessage 会被
    // 拒绝（返回 false），且原有的取消路径不受影响，最终仍能落到 cancelled。
    setChatTransport(createMockTransport({ chunkSizes: [1], stepDelayMs: 5 }))
    const store = useChatStore()

    const pending = store.submitMessage('你好')
    await new Promise((resolve) => setTimeout(resolve, 10))

    const localId = store.messages[1].localId
    expect(store.messages[1].status).not.toBe('complete')

    const started = await store.retryMessage(localId)
    expect(started).toBe(false)

    store.cancelMessage(localId)
    await pending

    expect(store.messages[1].status).toBe('cancelled')
    // 没有因为重入而多产生一轮对话。
    expect(store.messages).toHaveLength(2)
  })
})

describe('错误码分支', () => {
  // 表驱动穷举各类错误码应落到的消息状态。刻意覆盖「不可重试」的错误
  // （REQUEST_IN_PROGRESS、IDEMPOTENCY_KEY_REUSED）：它们仍然是 status
  // 'error'，只是不该在 UI 上给出重试按钮（见 ChatMessage.vue）。
  //
  // 这组测试的核心断言是 `status`：只要 Store 还在按字符串/name 比对而不是
  // `error.code` 分支，这里任何一行都会失败——因为 Task 1 之后一切错误的
  // `(error as Error).name` 都是同一个 `'AppError'`，字符串比对根本分不出
  // 这五种情形。
  const CASES = [
    { code: 'RATE_LIMITED', status: 'error', retryable: true },
    { code: 'LLM_BUDGET_EXCEEDED', status: 'error', retryable: true },
    { code: 'REQUEST_IN_PROGRESS', status: 'error', retryable: false },
    { code: 'IDEMPOTENCY_KEY_REUSED', status: 'error', retryable: false },
    { code: 'CANCELLED', status: 'cancelled', retryable: true },
  ] as const

  it.each(CASES)('$code → $status', async ({ code, status, retryable }) => {
    setChatTransport(async () => {
      throw new AppError(code, `模拟 ${code}`, { retryable })
    })
    const store = useChatStore()

    await store.submitMessage('你好')

    expect(store.messages[1].status).toBe(status)
    expect(store.messages[1].error?.code).toBe(code)
    // Store 只透传 AppError，不重新计算 retryable——这是「文案与可重试性都
    // 由错误对象本身携带，Store 不夹带自己的判断」的直接证据。
    expect(store.messages[1].error?.retryable).toBe(retryable)
  })
})

describe('loadConversation 被取代 / reset 时静默取消', () => {
  // 复现审查发现的问题：beginTrackedRequest 用同一个 key（LOAD_CONVERSATION_KEY）
  // 覆盖——连续点开两个会话，或加载途中触发 reset()（AssistantView 切换商家时
  // 会调用）——都会真的 abort 掉前一个还在途的 loadConversation 请求。改造前
  // loadConversation 只有 try/finally，abort 产生的拒绝会一路冒出去，砸在
  // ConversationDrawer.openConversation 那个没有 .catch 的 fire-and-forget
  // 调用点上，变成未处理的 Promise 拒绝。这里直接在 Store 层断言：被取消的
  // 那次调用本身不抛出，也不会污染取代它的那次调用已经写入的 state。

  /**
   * 用一个只在 `signal` 被 abort 时才 settle（reject）的 Promise 模拟真实
   * fetch/AbortController 的行为，避免依赖真实网络时序也能确定性复现
   * 「请求还没返回、controller 就被 abort」这条路径。若 `signal` 在这个函数
   * 被调用时已经是 aborted（两次调用之间没有 await，第二次的 beginTrackedRequest
   * 会在第一次的传输函数真正开始执行前就同步 abort 掉它），直接同步 reject，
   * 不注册监听器——否则永远不会 settle。
   */
  function hangUntilAborted(signal: AbortSignal): Promise<Response> {
    return new Promise<Response>((_resolve, reject) => {
      const rejectAsCancelled = () => reject(new DOMException('请求已取消', 'AbortError'))
      if (signal.aborted) {
        rejectAsCancelled()
        return
      }
      signal.addEventListener('abort', rejectAsCancelled)
    })
  }

  it('连续点开两个会话：被取代的第一次请求悄悄失败，不产生未处理拒绝，也不污染第二次的结果', async () => {
    const mock = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })
    setChatTransport(mock)
    const store = useChatStore()

    await store.submitMessage('昨天总 GMV 是多少？')
    const firstId = store.sessionId!
    store.reset()

    await store.submitMessage('我要货品上架，具体规则有吗？')
    const secondId = store.sessionId!
    store.reset()

    setChatTransport((req, signal) => {
      if (req.method === 'GET' && req.path === `/api/conversations/${firstId}`) {
        return hangUntilAborted(signal)
      }
      return mock(req, signal)
    })

    const firstLoad = store.loadConversation(firstId)
    // 同一个 LOAD_CONVERSATION_KEY：beginTrackedRequest 会先 abort 掉第一次还
    // 挂着的 controller，再登记自己的——这正是「连续点开两个会话」的真实路径。
    const secondLoad = store.loadConversation(secondId)

    await expect(firstLoad).resolves.toBeUndefined()
    await secondLoad

    expect(store.sessionId).toBe(secondId)
    expect(store.messages).toHaveLength(2)
    const assistant = store.messages.find((message) => message.role === 'assistant')
    expect(assistant?.origin).toBe('history')
  })

  it('加载途中触发 reset()（如切换商家）：请求被静默取消，不产生未处理拒绝', async () => {
    const mock = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })
    setChatTransport(mock)
    const store = useChatStore()

    await store.submitMessage('昨天总 GMV 是多少？')
    const conversationId = store.sessionId!
    store.reset()

    setChatTransport((req, signal) => {
      if (req.method === 'GET' && req.path === `/api/conversations/${conversationId}`) {
        return hangUntilAborted(signal)
      }
      return mock(req, signal)
    })

    const pendingLoad = store.loadConversation(conversationId)
    store.reset() // 模拟 AssistantView 在切换商家时调用

    await expect(pendingLoad).resolves.toBeUndefined()
    expect(store.messages).toEqual([])
    expect(store.sessionId).toBeUndefined()
  })
})

describe('消息 origin 与历史消息重试', () => {
  it('submitMessage 产生的消息 origin 为 live', async () => {
    const store = useChatStore()

    await store.submitMessage('昨天总 GMV 是多少？')

    expect(store.messages[0].origin).toBe('live')
    expect(store.messages[1].origin).toBe('live')
  })

  it('历史消息不可重试', async () => {
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const sessionId = store.sessionId!

    await store.loadConversation(sessionId)
    const assistant = store.messages.find((message) => message.role === 'assistant')!

    expect(assistant.origin).toBe('history')
    expect(await store.retryMessage(assistant.localId)).toBe(false)
    // 拒绝重试之外，消息本身没有被误置成别的状态。
    expect(assistant.status).toBe('complete')
  })
})
