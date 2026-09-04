import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setLocaleProvider } from '@/api/credentials'
import { AppError } from '@/api/errors'
import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport, type TransportRequest } from '@/api/transport'

import { useChatStore } from './chat'
import { useLocaleStore } from './locale'

beforeEach(() => {
  setActivePinia(createPinia())
  setChatTransport(createMockTransport({ chunkSizes: [4], stepDelayMs: 0 }))
})

afterEach(() => {
  setLocaleProvider(undefined)
})

/** 手动控制 settle 时机的 Promise，用来构造"谁先谁后返回"的确定性竞态。 */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function conversationListPayload(item: { id: string; title: string }) {
  return {
    items: [{ id: item.id, title: item.title, created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' }],
    limit: 20,
    offset: 0,
    localization_degraded: false,
    localization_degraded_reason: null,
  }
}

/**
 * `submitChat`（`api/chat.ts`）固定用 `accept: 'text/event-stream'` 请求，
 * 手写的替身 transport 也必须按 SSE 帧格式编码响应体，不能直接
 * `Response.json(...)`——`readChatStream` 只认 `event:`/`data:` 帧，收到
 * 普通 JSON body 会因为找不到 `done`/`error` 帧而抛 `ChatStreamInterruptedError`，
 * 在 `replayRoundInNewLocale`/`continueRoundInNewLocale` 的空 catch 里被
 * 默默吞掉，现象是"什么都没发生"，很容易被误判成别的 bug。
 */
function sseChatResponse(payload: Record<string, unknown>): Response {
  const text = `event: done\ndata: ${JSON.stringify(payload)}\n\n`
  return new Response(new TextEncoder().encode(text), {
    status: 200,
    headers: { 'content-type': 'text/event-stream; charset=utf-8' },
  })
}

function installFeedbackTransport(
  onFeedback: (request: TransportRequest, signal: AbortSignal) => Promise<Response>,
): void {
  const chatTransport = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })
  setChatTransport((request, signal) => {
    if (request.method === 'POST' && request.path.endsWith('/feedback')) {
      return onFeedback(request, signal)
    }
    return chatTransport(request, signal)
  })
}

function feedbackResponse(request: TransportRequest): Response {
  const body = request.body as { is_adopted: boolean; reaction: 'LIKE' | 'DISLIKE' | null }
  return Response.json({
    answer_id: request.path.split('/').at(-2),
    is_adopted: body.is_adopted,
    reaction: body.reaction,
  })
}

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

describe('回答反馈', () => {
  it('采纳后点赞会提交完整状态并保留采纳', async () => {
    const requests: TransportRequest[] = []
    installFeedbackTransport(async (request) => {
      requests.push(request)
      return feedbackResponse(request)
    })
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const localId = store.messages[1].localId

    await store.sendFeedback(localId, { type: 'ADOPT' })
    await store.sendFeedback(localId, { type: 'REACT', reaction: 'LIKE' })

    expect(requests.map((request) => request.body)).toEqual([
      { is_adopted: true, reaction: null },
      { is_adopted: true, reaction: 'LIKE' },
    ])
    expect(store.messages[1].feedback).toEqual({ isAdopted: true, reaction: 'LIKE' })
  })

  it('点赞与点踩可以互相切换', async () => {
    installFeedbackTransport(async (request) => feedbackResponse(request))
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const localId = store.messages[1].localId

    await store.sendFeedback(localId, { type: 'REACT', reaction: 'LIKE' })
    await store.sendFeedback(localId, { type: 'REACT', reaction: 'DISLIKE' })

    expect(store.messages[1].feedback).toEqual({ isAdopted: false, reaction: 'DISLIKE' })
  })

  it('成功后重复点击同一反馈是 no-op', async () => {
    let calls = 0
    installFeedbackTransport(async (request) => {
      calls += 1
      return feedbackResponse(request)
    })
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const localId = store.messages[1].localId

    await store.sendFeedback(localId, { type: 'ADOPT' })
    await store.sendFeedback(localId, { type: 'ADOPT' })

    expect(calls).toBe(1)
  })

  it('失败保留用户意图且同一按钮可以再次点击重试', async () => {
    let calls = 0
    installFeedbackTransport(async (request) => {
      calls += 1
      if (calls === 1) throw new AppError('NETWORK', '网络不可用', { retryable: true })
      return feedbackResponse(request)
    })
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const localId = store.messages[1].localId

    await store.sendFeedback(localId, { type: 'ADOPT' })
    expect(store.messages[1].feedback).toEqual({ isAdopted: true, reaction: null })
    expect(store.messages[1].feedbackPersisted).not.toBe(true)
    expect(store.messages[1].feedbackError?.code).toBe('NETWORK')

    await store.sendFeedback(localId, { type: 'ADOPT' })

    expect(calls).toBe(2)
    expect(store.messages[1].feedbackPersisted).toBe(true)
    expect(store.messages[1].feedbackError).toBeUndefined()
  })

  it('一次失败后点另一个按钮会带上之前未确认的改动', async () => {
    const bodies: unknown[] = []
    installFeedbackTransport(async (request) => {
      bodies.push(request.body)
      if (bodies.length === 1) {
        throw new AppError('NETWORK', '网络不可用', { retryable: true })
      }
      return feedbackResponse(request)
    })
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const localId = store.messages[1].localId

    await store.sendFeedback(localId, { type: 'ADOPT' })
    await store.sendFeedback(localId, { type: 'REACT', reaction: 'LIKE' })

    expect(bodies).toEqual([
      { is_adopted: true, reaction: null },
      { is_adopted: true, reaction: 'LIKE' },
    ])
  })

  it('服务端确认标志是粘性的，后续失败不会清除', async () => {
    let calls = 0
    installFeedbackTransport(async (request) => {
      calls += 1
      if (calls === 2) throw new AppError('NETWORK', '网络不可用', { retryable: true })
      return feedbackResponse(request)
    })
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const localId = store.messages[1].localId

    await store.sendFeedback(localId, { type: 'ADOPT' })
    await store.sendFeedback(localId, { type: 'REACT', reaction: 'DISLIKE' })

    expect(store.messages[1].feedback).toEqual({ isAdopted: true, reaction: 'DISLIKE' })
    expect(store.messages[1].feedbackPersisted).toBe(true)
    expect(store.messages[1].feedbackError?.code).toBe('NETWORK')
  })

  it('缺少回答 ID 时不提交反馈', async () => {
    let calls = 0
    installFeedbackTransport(async (request) => {
      calls += 1
      return feedbackResponse(request)
    })
    const store = useChatStore()
    store.messages.push({
      localId: 'history-without-answer',
      clientRequestId: 'history-without-answer-request',
      role: 'assistant',
      text: '旧版历史回答',
      createdAt: '2026-08-01T00:00:00Z',
      status: 'complete',
      steps: [],
      origin: 'history',
    })
    const assistant = store.messages[0]

    await store.sendFeedback(assistant.localId, { type: 'ADOPT' })

    expect(calls).toBe(0)
    expect(assistant.feedback).toBeUndefined()
  })

  it('在途时拒绝重入，reset 会中止反馈请求', async () => {
    let calls = 0
    let aborted = false
    installFeedbackTransport(
      (request, signal) =>
        new Promise<Response>((resolve, reject) => {
          calls += 1
          signal.addEventListener('abort', () => {
            aborted = true
            reject(new DOMException('请求已取消', 'AbortError'))
          })
          void request
          void resolve
        }),
    )
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const localId = store.messages[1].localId

    const pending = store.sendFeedback(localId, { type: 'ADOPT' })
    await vi.waitFor(() => expect(store.messages[1].feedbackPending).toBe(true))
    await store.sendFeedback(localId, { type: 'REACT', reaction: 'LIKE' })
    expect(calls).toBe(1)

    store.reset()

    await expect(pending).resolves.toBeUndefined()
    expect(aborted).toBe(true)
    expect(store.messages).toEqual([])
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

  it('实时助手消息只用 answer.id 标识回答，不混入后端消息 ID', async () => {
    const store = useChatStore()

    await store.submitMessage('昨天总 GMV 是多少？')

    const assistant = store.messages[1]
    expect(assistant.answer?.id).toBeTruthy()
    expect(assistant.messageId).toBeUndefined()
  })

  it('历史助手消息装配服务端回答载荷、步骤和当前反馈状态', async () => {
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')

    await store.loadConversation(store.sessionId!)

    expect(store.messages.every((message) => Boolean(message.messageId))).toBe(true)
    const assistant = store.messages.find((message) => message.role === 'assistant')!
    expect(assistant.messageId).toBeTruthy()
    expect(assistant.answer?.thinkingSteps.length).toBeGreaterThan(0)
    expect(assistant.steps).toEqual([])
    expect(assistant.feedback).toEqual({ isAdopted: false, reaction: null })
    expect(assistant.feedbackPersisted).toBe(true)
  })

  it('历史会话重载后保留服务端确认的反馈状态', async () => {
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    const sessionId = store.sessionId!
    const liveAssistant = store.messages.find((message) => message.role === 'assistant')!

    await store.sendFeedback(liveAssistant.localId, { type: 'ADOPT' })
    await store.loadConversation(sessionId)

    const historyAssistant = store.messages.find((message) => message.role === 'assistant')!
    expect(historyAssistant.feedback).toEqual({ isAdopted: true, reaction: null })
    expect(historyAssistant.feedbackPersisted).toBe(true)
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

describe('语言切换：epoch 竞态防护（Task 11 Step 2）', () => {
  it('中文请求较晚返回、英语请求较早返回：切到英语后中文响应被丢弃，Store 最终只含英语数据', async () => {
    const store = useChatStore()
    const localeStore = useLocaleStore()

    // 先正常拉一次会话列表（中文），让 conversationsLoaded 变 true——
    // 语言切换只重新加载"已经在用"的数据，这是触发第二次 loadConversations()
    // 的前提。
    setChatTransport(async () => Response.json(conversationListPayload({ id: 'zh-seed', title: '中文种子' })))
    await store.loadConversations()

    const zh = deferred<Response>()
    const en = deferred<Response>()
    setLocaleProvider(() => localeStore.locale)
    // 按"第几次调用"分发响应，不按调用那一刻读到的 locale 分发：
    // `store.loadConversations()` 内部要经过若干次 await（resolveTransport
    // 本身也是 async）才真正执行到这个 transport 函数，如果在这段真实的
    // 微任务延迟里去读 `localeStore.locale`，读到的可能已经是切换后的新值——
    // 这不是这条测试要验证的东西（那是 transport.spec.ts 的职责），这里只
    // 关心"先发出的请求" vs "语言切换后发出的请求"谁的响应先到、Store 是否
    // 按 epoch 正确取舍，用调用顺序钉死两次请求分别对应哪个 Deferred。
    let callCount = 0
    setChatTransport(async () => {
      callCount += 1
      return callCount === 1 ? zh.promise : en.promise
    })

    // 模拟"中文这次请求还没回来，用户就切到了英语"：先手动发起一次中文请求
    // （不经过 reloadForLocale，代表任意一次仍在途的中文刷新），再切语言。
    const staleZhLoad = store.loadConversations()
    localeStore.setLocale('en-US') // 触发 watch → reloadForLocale()，epoch += 1，发出新的英语请求

    // 英语先回来。
    en.resolve(Response.json(conversationListPayload({ id: 'en-1', title: 'English conversation' })))
    await vi.waitFor(() => expect(store.conversations).toEqual([expect.objectContaining({ id: 'en-1' })]))

    // 中文后回来——必须被丢弃，不能覆盖已经写入的英语数据。
    zh.resolve(Response.json(conversationListPayload({ id: 'zh-late', title: '过期的中文响应' })))
    await staleZhLoad
    // 给一次事件循环，确认"迟到的中文响应"确实被处理过（而不是还没跑到那一行）。
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.conversations).toEqual([expect.objectContaining({ id: 'en-1', title: 'English conversation' })])
  })

  it('会话列表的竞态丢弃不影响当前会话（sessionId/messages）与原始发送状态', async () => {
    const store = useChatStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)

    await store.submitMessage('昨天总 GMV 是多少？')
    const sessionIdBefore = store.sessionId
    const messagesBefore = store.messages.length

    setChatTransport(async () => Response.json(conversationListPayload({ id: 'zh-seed', title: '中文种子' })))
    await store.loadConversations()

    const zh = deferred<Response>()
    const en = deferred<Response>()
    setChatTransport(async (request) => {
      if (request.path.startsWith('/api/conversations') && request.method === 'GET') {
        return localeStore.locale === 'en-US' ? en.promise : zh.promise
      }
      // 语言切换也会尝试重放/续接当前会话里已完成的 live 轮次
      // （replayRoundInNewLocale）；这条路径在本用例里不是断言重点，
      // 给一个立刻挂起的 Promise，不让它干扰下面对会话列表竞态的断言。
      return new Promise<Response>(() => {})
    })

    localeStore.setLocale('en-US')
    en.resolve(Response.json(conversationListPayload({ id: 'en-1', title: 'English conversation' })))
    await vi.waitFor(() => expect(store.conversations.length).toBeGreaterThan(0))
    zh.resolve(Response.json(conversationListPayload({ id: 'zh-late', title: '过期中文' })))
    await new Promise((resolve) => setTimeout(resolve, 0))

    // 当前会话（sessionId）和已有消息数量不受这条"只影响会话列表"的竞态波及。
    expect(store.sessionId).toBe(sessionIdBefore)
    expect(store.messages.length).toBe(messagesBefore)
  })
})

describe('语言切换：SSE 轮次续接/重放，不重放仍在 PROCESSING 的轮次（Task 11 Step 3）', () => {
  it('切换语言时命中仍在 PROCESSING 的轮次：不用同一 clientRequestId 重放，改用会话详情拿本地化回答', async () => {
    const store = useChatStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)

    // 先完成第一轮，拿到 sessionId——continueRoundInNewLocale 需要已知的
    // sessionId 才能查会话详情。
    await store.submitMessage('你好')
    const sessionId = store.sessionId!

    const postCallCountByClientRequestId = new Map<string, number>()
    const round2Post = deferred<Response>()
    const detail = deferred<Response>()
    let round2ClientRequestId = ''

    setChatTransport(async (request: TransportRequest) => {
      if (request.path === '/api/chat' && request.method === 'POST') {
        const body = request.body as { client_request_id: string }
        postCallCountByClientRequestId.set(
          body.client_request_id,
          (postCallCountByClientRequestId.get(body.client_request_id) ?? 0) + 1,
        )
        if (body.client_request_id === round2ClientRequestId) {
          // 第二轮的 POST 永不 settle：模拟服务端仍在 PROCESSING。
          return round2Post.promise
        }
        // 其它 client_request_id（第一轮语言切换时的幂等重放）立刻给一个
        // 简单响应，不让它干扰本用例只关心第二轮的断言。
        return sseChatResponse({
          id: crypto.randomUUID(),
          session_id: sessionId,
          displayed_user_message: 'Hello',
          answer: 'replayed',
          answer_mode: 'CHAT',
          category: 'UNKNOWN',
          thinking_steps: [],
          quality_status: 'NOT_RUN',
          quality_attempts: 0,
          quality_notes: [],
          analysis_sources: ['NONE'],
          degraded: false,
          degraded_reason: null,
          suggestions: [],
          suggestion_alternates: [],
          created_at: new Date().toISOString(),
        })
      }
      if (request.path === `/api/conversations/${sessionId}` && request.method === 'GET') {
        return detail.promise
      }
      throw new Error(`未预期的请求：${request.method} ${request.path}`)
    })

    // 发起第二轮，但不 await——它会一直挂在 round2Post 上，模拟"仍在处理"。
    const pendingRound2 = store.submitMessage('最近 7 天退货量趋势')
    await vi.waitFor(() => expect(store.messages.at(-1)?.status).toBe('pending'))
    round2ClientRequestId = store.messages.at(-1)!.clientRequestId
    const round2AssistantLocalId = store.messages.at(-1)!.localId

    localeStore.setLocale('en-US')

    // 断言："生成中"占位状态保持，且没有用同一 clientRequestId 立刻重放。
    await vi.waitFor(() => {
      expect(store.messages.find((m) => m.localId === round2AssistantLocalId)?.status).toBe('pending')
    })
    expect(postCallCountByClientRequestId.get(round2ClientRequestId)).toBe(1)

    // 服务端其实已经处理完了：通过会话详情把本地化后的完整回答和
    // displayed_user_message 交回来。
    detail.resolve(
      Response.json({
        id: sessionId,
        title: 'Return trend',
        messages: [
          { id: crypto.randomUUID(), role: 'user', content: '你好', created_at: '2026-08-01T00:00:00Z' },
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: '已完成结构化理解。',
            created_at: '2026-08-01T00:00:01Z',
            answer_payload: {
              answer_id: crypto.randomUUID(),
              answer_mode: 'CHAT',
              thinking_steps: [],
              quality_status: 'NOT_RUN',
              quality_attempts: 0,
              quality_notes: [],
              degraded: false,
              degraded_reason: null,
              is_adopted: false,
              reaction: null,
              columns: [],
              total_rows: null,
              truncated: null,
            },
          },
          {
            id: crypto.randomUUID(),
            role: 'user',
            content: 'Return trend over the last 7 days',
            created_at: '2026-08-01T00:00:02Z',
          },
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: 'Return trend analysis in English.',
            created_at: '2026-08-01T00:00:03Z',
            answer_payload: {
              answer_id: crypto.randomUUID(),
              answer_mode: 'METRIC',
              thinking_steps: [],
              quality_status: 'PASSED',
              quality_attempts: 1,
              quality_notes: [],
              degraded: false,
              degraded_reason: null,
              is_adopted: false,
              reaction: null,
              columns: [],
              total_rows: null,
              truncated: null,
            },
          },
        ],
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:03Z',
        next_message_cursor: null,
        has_more_messages: false,
        localization_degraded: false,
        localization_degraded_reason: null,
      }),
    )

    await vi.waitFor(() => {
      expect(store.messages.find((m) => m.localId === round2AssistantLocalId)?.status).toBe('complete')
    })
    const round2Assistant = store.messages.find((m) => m.localId === round2AssistantLocalId)!
    expect(round2Assistant.text).toBe('Return trend analysis in English.')
    // 用户气泡改用 displayed_user_message（会话详情里已经本地化过的 content），
    // 不保留乐观的源语言气泡。
    const round2User = store.messages[store.messages.indexOf(round2Assistant) - 1]
    expect(round2User.text).toBe('Return trend over the last 7 days')
    // 全程只提交过一次这个 clientRequestId，没有在仍是 PROCESSING 时重放。
    expect(postCallCountByClientRequestId.get(round2ClientRequestId)).toBe(1)

    // 让第一轮悬而未决的重放 Promise 有地方去，避免测试结束时留下未处理拒绝。
    round2Post.resolve(new Response(null, { status: 599 }))
    await pendingRound2.catch(() => {})
  })

  it('切换语言时命中已 SUCCEEDED 的轮次：同 clientRequestId 重放合法，命中幂等分支拿到本地化副本，且不经过 pending/streaming', async () => {
    const store = useChatStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)

    await store.submitMessage('你好')
    const clientRequestId = store.messages[1].clientRequestId
    const sessionId = store.sessionId!
    const statusesDuringReplay: string[] = []

    const postCallCountByClientRequestId = new Map<string, number>()
    setChatTransport(async (request: TransportRequest) => {
      if (request.path === '/api/chat' && request.method === 'POST') {
        const body = request.body as { client_request_id: string }
        postCallCountByClientRequestId.set(
          body.client_request_id,
          (postCallCountByClientRequestId.get(body.client_request_id) ?? 0) + 1,
        )
        return sseChatResponse({
          id: crypto.randomUUID(),
          session_id: sessionId,
          displayed_user_message: 'Hello',
          answer: 'Hello! How can I help?',
          answer_mode: 'CHAT',
          category: 'UNKNOWN',
          thinking_steps: [],
          quality_status: 'NOT_RUN',
          quality_attempts: 0,
          quality_notes: [],
          analysis_sources: ['NONE'],
          degraded: false,
          degraded_reason: null,
          suggestions: [],
          suggestion_alternates: [],
          created_at: new Date().toISOString(),
        })
      }
      throw new Error(`未预期的请求：${request.method} ${request.path}`)
    })

    // 在切换语言触发重放期间持续采样 assistant.status，证明幂等命中不会
    // 让 UI 闪回"生成中"。
    const assistantLocalId = store.messages[1].localId
    const sampler = setInterval(() => {
      const assistant = store.messages.find((m) => m.localId === assistantLocalId)
      if (assistant) statusesDuringReplay.push(assistant.status)
    }, 0)

    localeStore.setLocale('en-US')
    await vi.waitFor(() => expect(store.messages[1].text).toBe('Hello! How can I help?'))
    clearInterval(sampler)

    // 原始提交走的是 beforeEach 装好的默认 Mock transport（不在这张计数表
    // 里）；这里的计数表只在切换语言之后才安装，因此“1”就代表“语言切换
    // 触发了恰好一次同 clientRequestId 的重放请求”——既不是 0（没重放，
    // 界面停在旧语言），也不是 2+（重复重放）。
    expect(postCallCountByClientRequestId.get(clientRequestId)).toBe(1)
    expect(store.messages[1].status).toBe('complete')
    expect(statusesDuringReplay.every((status) => status === 'complete')).toBe(true)
    // 用户气泡也换成这次重放返回的 displayed_user_message。
    expect(store.messages[0].text).toBe('Hello')
  })
})

describe('会话详情分页、翻译重试与降级标记（Task 11 Step 6 / Task 10B 缺口收尾）', () => {
  function detailResponse(opts: {
    messages: Array<{ id: string; role: 'user' | 'assistant'; content: string; createdAt: string }>
    nextCursor: string | null
    hasMore: boolean
    degraded: boolean
    degradedReason?: string | null
  }): Response {
    return Response.json({
      id: 'conv-1',
      title: '示例会话',
      messages: opts.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        created_at: m.createdAt,
      })),
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:10:00Z',
      next_message_cursor: opts.nextCursor,
      has_more_messages: opts.hasMore,
      localization_degraded: opts.degraded,
      localization_degraded_reason: opts.degradedReason ?? null,
    })
  }

  it('loadConversation 首次打开会带回 hasMoreMessages/nextMessageCursor/localizationDegraded', async () => {
    const store = useChatStore()
    setChatTransport(async (request) => {
      if (request.path.startsWith('/api/conversations/conv-1')) {
        return detailResponse({
          messages: [{ id: 'm2', role: 'assistant', content: '答案', createdAt: '2026-08-01T00:01:00Z' }],
          nextCursor: 'cursor-1',
          hasMore: true,
          degraded: true,
          degradedReason: '翻译预算已用尽',
        })
      }
      throw new Error(`未预期的请求：${request.path}`)
    })

    await store.loadConversation('conv-1')

    expect(store.hasMoreMessages).toBe(true)
    expect(store.nextMessageCursor).toBe('cursor-1')
    expect(store.localizationDegraded).toBe(true)
    expect(store.localizationDegradedReason).toBe('翻译预算已用尽')
  })

  it('loadMoreMessages 用 nextMessageCursor 请求更早一页，合并到已展示消息最前面且按时间正序', async () => {
    const store = useChatStore()
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      if (request.path === '/api/conversations/conv-1') {
        return detailResponse({
          messages: [{ id: 'm2', role: 'assistant', content: '较新的回答', createdAt: '2026-08-01T00:05:00Z' }],
          nextCursor: 'cursor-1',
          hasMore: true,
          degraded: false,
        })
      }
      if (request.path === '/api/conversations/conv-1?message_before=cursor-1') {
        return detailResponse({
          messages: [{ id: 'm1', role: 'user', content: '较早的问题', createdAt: '2026-08-01T00:00:00Z' }],
          nextCursor: null,
          hasMore: false,
          degraded: false,
        })
      }
      throw new Error(`未预期的请求：${request.path}`)
    })

    await store.loadConversation('conv-1')
    await store.loadMoreMessages()

    expect(store.messages.map((m) => m.text)).toEqual(['较早的问题', '较新的回答'])
    expect(store.hasMoreMessages).toBe(false)
    expect(store.nextMessageCursor).toBeUndefined()
    expect(requests.some((r) => r.path.includes('message_before=cursor-1'))).toBe(true)
  })

  it('hasMoreMessages 为 false 时 loadMoreMessages 是 no-op，不发多余请求', async () => {
    const store = useChatStore()
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return detailResponse({ messages: [], nextCursor: null, hasMore: false, degraded: false })
    })

    await store.loadConversation('conv-1')
    const callsAfterOpen = requests.length
    await store.loadMoreMessages()

    expect(requests.length).toBe(callsAfterOpen)
  })

  it('retryLocalization 用同一游标（首页）重新拉当前页，翻译成功后覆盖占位内容', async () => {
    const store = useChatStore()
    let call = 0
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      call += 1
      if (call === 1) {
        return detailResponse({
          messages: [
            { id: 'm1', role: 'assistant', content: '[翻译降级占位]', createdAt: '2026-08-01T00:00:00Z' },
          ],
          nextCursor: null,
          hasMore: false,
          degraded: true,
          degradedReason: '翻译预算已用尽',
        })
      }
      return detailResponse({
        messages: [
          { id: 'm1', role: 'assistant', content: '已成功翻译的正文', createdAt: '2026-08-01T00:00:00Z' },
        ],
        nextCursor: null,
        hasMore: false,
        degraded: false,
      })
    })

    await store.loadConversation('conv-1')
    expect(store.localizationDegraded).toBe(true)
    expect(store.messages[0].text).toBe('[翻译降级占位]')

    await store.retryLocalization()

    expect(store.localizationDegraded).toBe(false)
    expect(store.messages[0].text).toBe('已成功翻译的正文')
    // 两次请求路径相同（都是第一页，不带 before）——「翻译重试用同一游标
    // 覆盖该页」的直接证据。
    expect(requests[0].path).toBe(requests[1].path)
  })

  it('conversationsLocalizationDegraded 反映会话列表接口返回的降级标记，供抽屉渲染重试入口', async () => {
    const store = useChatStore()
    setChatTransport(async () =>
      Response.json({
        items: [],
        limit: 20,
        offset: 0,
        localization_degraded: true,
        localization_degraded_reason: '标题翻译预算已用尽',
      }),
    )

    await store.loadConversations()

    expect(store.conversationsLocalizationDegraded).toBe(true)
    expect(store.conversationsLocalizationDegradedReason).toBe('标题翻译预算已用尽')
  })
})
