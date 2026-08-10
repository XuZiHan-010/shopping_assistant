import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  deleteConversation,
  getConversation,
  listConversations,
  submitChat,
  type ConversationSummaryView,
} from '@/api/chat'
import { toAppError } from '@/api/errors'
import type { ChatAnswer, ChatMessage, ThinkingStep } from '@/types/chat'

function newMessage(
  role: ChatMessage['role'],
  text: string,
  clientRequestId: string,
  status: ChatMessage['status'],
): ChatMessage {
  return {
    localId: crypto.randomUUID(),
    clientRequestId,
    role,
    text,
    createdAt: new Date().toISOString(),
    status,
    steps: [],
    origin: 'live',
  }
}

// 会话列表相关的三个请求（列表、详情、删除）各自共用固定 key，与
// per-message 的 `controllers` 条目（key 是 `assistant.localId`，UUID）不会
// 撞车。命名控制器让「切换商家」「连续点开不同会话」这类后发请求覆盖前一次
// 时，能主动 abort 还在途的旧请求——否则旧商家/旧会话的响应可能比新请求晚
// 到，把新请求的结果覆盖回旧数据。
const LOAD_CONVERSATIONS_KEY = '__load-conversations__'
const LOAD_CONVERSATION_KEY = '__load-conversation__'
const REMOVE_CONVERSATION_KEY = '__remove-conversation__'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string | undefined>(undefined)
  const selectedRoundId = ref<string | undefined>(undefined)
  const controllers = new Map<string, AbortController>()

  const isEmptyConversation = computed(() => messages.value.length === 0)

  /** 有任何一轮在途。submitMessage 与输入区都靠它封住并发提交。 */
  const isBusy = computed(() =>
    messages.value.some(
      (message) => message.status === 'pending' || message.status === 'streaming',
    ),
  )

  const assistantRounds = computed(() =>
    messages.value.filter((message) => message.role === 'assistant'),
  )

  const currentAnswer = computed<ChatAnswer | undefined>(() => {
    const target =
      assistantRounds.value.find((message) => message.localId === selectedRoundId.value) ??
      assistantRounds.value.at(-1)
    return target?.answer
  })

  function selectRound(localId: string): void {
    selectedRoundId.value = localId
  }

  /** 注册一个命名请求：若同 key 下已有在途请求，先 abort 它再登记新的。 */
  function beginTrackedRequest(key: string): AbortController {
    controllers.get(key)?.abort()
    const controller = new AbortController()
    controllers.set(key, controller)
    return controller
  }

  /**
   * 收尾时按身份而非 key 删除：若这个 key 已经被更晚发起的同类请求替换过
   * （替换发生在 beginTrackedRequest），说明 map 里现在存的是别人的
   * controller，这里不能删——删了 reset() 就再也 abort 不到那个仍在途的
   * 新请求。
   */
  function endTrackedRequest(key: string, controller: AbortController): void {
    if (controllers.get(key) === controller) controllers.delete(key)
  }

  function reset(): void {
    for (const controller of controllers.values()) controller.abort()
    controllers.clear()
    messages.value = []
    sessionId.value = undefined
    selectedRoundId.value = undefined
  }

  async function runRound(assistant: ChatMessage, text: string): Promise<void> {
    const controller = new AbortController()
    controllers.set(assistant.localId, controller)

    try {
      const answer = await submitChat(
        {
          message: text,
          sessionId: sessionId.value,
          clientRequestId: assistant.clientRequestId,
        },
        {
          onStep(step: ThinkingStep) {
            // 第一个 step 到达即进入 streaming，这是「1 秒内可见处理状态」的落点。
            assistant.status = 'streaming'
            assistant.steps.push(step)
          },
        },
        controller.signal,
      )

      assistant.answer = answer
      assistant.id = answer.id
      assistant.text = answer.answer
      assistant.status = 'complete'
      sessionId.value = answer.sessionId
      selectedRoundId.value = assistant.localId
    } catch (raw) {
      // 错误码分支，不是字符串/name 比对：Task 1 把一切错误统一包成
      // AppError 后，`(error as Error).name` 恒为 `'AppError'`，原先靠
      // `name === 'AbortError'` 判取消的写法会静默失效——用户每次点「停止」
      // 都会看到「出错了」而不是「已取消」。`toAppError` 是幂等的，raw 已经
      // 是 AppError 时直接透传。
      const error = toAppError(raw)
      assistant.status = error.code === 'CANCELLED' ? 'cancelled' : 'error'
      assistant.error = error
    } finally {
      controllers.delete(assistant.localId)
    }
  }

  // 与 retryMessage 不同，submitMessage 每次都用 newMessage() 生成全新的
  // localId，controllers 里不会出现 key 覆盖，天然不存在同类重入问题——不需要
  // 额外的守卫。
  async function submitMessage(text: string): Promise<boolean> {
    const content = text.trim()
    if (!content) return false

    // 上一轮还在跑时不允许再发。两轮并发会同时读到尚未回填的 sessionId，各自
    // 在服务端开一个新会话，前端却把两串回答混在同一条消息流里——之后无论保留
    // 哪个 sessionId 都是错的。与 retryMessage 的重入保护同源，返回 boolean 让
    // 调用方知道这次点击是不是被拒了，而不是静默吞掉。
    if (isBusy.value) return false

    const clientRequestId = crypto.randomUUID()
    const user = newMessage('user', content, clientRequestId, 'complete')
    const rawAssistant = newMessage('assistant', '', clientRequestId, 'pending')
    messages.value.push(user, rawAssistant)

    // 陷阱：push 进去的是原始对象；push 完之后 messages.value 是响应式数组，
    // 但 rawAssistant 变量本身仍然指向未经代理的原始对象。如果直接把
    // rawAssistant 传给 runRound，里面对 status/steps/answer 的赋值都发生在
    // 原始对象上，不经过响应式代理的 set 陷阱，不会触发依赖更新——组件读到的
    // 数值最终是对的（因为代理只是转发到同一个原始对象），但从来不会因为这些
    // 赋值而重新渲染，界面就会永远停在 push 那一刻的状态（例如卡在「正在准备」
    // 且看不到最终答案）。这里必须重新从 messages.value 里取出代理版本再传下去
    // ——与 retryMessage 的做法一致。
    const assistant = messages.value.find((message) => message.localId === rawAssistant.localId)!

    await runRound(assistant, content)
    return true
  }

  function cancelMessage(localId: string): void {
    // 真正中断底层流，不只是 UI 上隐藏——否则后端会继续跑完并计费。
    controllers.get(localId)?.abort()
  }

  /**
   * 返回是否真的启动了新一轮，而不是静默吞掉——重入保护如果不给调用方任何
   * 反馈，UI（未来的重试按钮）就无从知道这次点击是不是白点了。
   */
  async function retryMessage(localId: string): Promise<boolean> {
    const assistant = messages.value.find((message) => message.localId === localId)
    if (!assistant || assistant.role !== 'assistant') return false

    // 历史消息不可重试：loadConversation 回填的消息从未在本次会话里真正
    // 发起过请求（没有 clientRequestId 对应的原始请求上下文、没有陪跑的
    // AbortController），"重试" 无从谈起，UI 也不应该给出这个入口。
    if (assistant.origin === 'history') return false

    // 重入保护：retryMessage 复用 assistant.localId 作为 controllers 的 key（与
    // 首次 submitMessage 时的 runRound 相同）。若上一轮还在 pending/streaming，
    // 这里再跑一次会用同一个 key 覆盖 controllers 里的旧 AbortController；旧那
    // 轮结束时的 finally 又会把新 controller 一并 delete 掉——此后 cancelMessage
    // 就静默失效了（用户以为取消了，请求其实还在跑、还在计费）。所以必须在还
    // 没跑之前就拦下来，而不是靠调用方（UI）自觉。
    if (assistant.status === 'pending' || assistant.status === 'streaming') return false

    // messages 只由 submitMessage 成对 push（user 紧跟 assistant），没有其他地方
    // 会往中间插入或删除消息，所以「assistant 的前一条就是对应的 user 消息」这
    // 个假设目前总成立。
    const questionIndex = messages.value.findIndex((message) => message.localId === localId) - 1
    const question = messages.value[questionIndex]
    if (!question) return false

    // 复用原 clientRequestId：后端据此可能直接返回已完成结果，避免重复计费（§5.9）。
    assistant.status = 'pending'
    assistant.error = undefined
    assistant.steps = []

    await runRound(assistant, question.text)
    return true
  }

  const conversations = ref<ConversationSummaryView[]>([])

  async function loadConversations(): Promise<void> {
    const controller = beginTrackedRequest(LOAD_CONVERSATIONS_KEY)
    try {
      conversations.value = await listConversations(controller.signal)
    } finally {
      endTrackedRequest(LOAD_CONVERSATIONS_KEY, controller)
    }
  }

  async function loadConversation(id: string): Promise<void> {
    const controller = beginTrackedRequest(LOAD_CONVERSATION_KEY)
    let detail: Awaited<ReturnType<typeof getConversation>>
    try {
      detail = await getConversation(id, controller.signal)
    } catch (raw) {
      // beginTrackedRequest 用同一个 key 覆盖：连续点开两个会话，或在加载途中
      // 切换商家触发 reset()，都会 abort 掉这个还在途的请求。这不是用户可感知
      // 的错误——真正生效的是那个更晚的请求（或 reset() 本身），它会自己把
      // state 收拾成对的样子。这里必须静默吞掉，否则会变成一个未处理的
      // Promise 拒绝，一路冒到 ConversationDrawer.openConversation 那个
      // fire-and-forget 的 `@click` 调用点（它不在本任务改动范围内，但这是本次
      // 请求生命周期改动——beginTrackedRequest 真正 abort 前一个请求——的直接
      // 后果，必须在源头堵住，而不是指望每个调用方自己记得 catch）。
      if (toAppError(raw).code === 'CANCELLED') return
      throw raw
    } finally {
      endTrackedRequest(LOAD_CONVERSATION_KEY, controller)
    }

    // 顺序要紧：reset() 会清空 sessionId，放到赋值之后会把刚设好的会话 ID 抹掉。
    reset()
    // `detail.id` 直接当作后续 /api/chat 的 session_id 使用，前提是两者共享
    // 同一个 UUID 空间——已通过读后端源码确认成立：
    // `backend/app/services/chat_service.py::_resolve_conversation` 把
    // `ChatRequest.session_id` 直接当 `conversation_id` 去查
    // （`get_for_merchant` / `require_conversation`），而
    // `backend/app/api/routes/chat.py::get_conversation`（本 store 调用的
    // `getConversation`）返回的 `ConversationDetailResponse.id` 正是同一张
    // `Conversation` 表的 `id`。所以「会话 id 就是 session_id」这个假设成立，
    // 不需要额外的 id 映射。
    sessionId.value = detail.id
    // 历史消息没有流式过程，直接落到终态；answer 留空，侧栏因此显示空状态而不是
    // 上一轮的残留——重新提问才会有完整回答载荷。origin 标为 'history'：
    // retryMessage 靠它拒绝对历史消息发起重试（这些消息在本次会话里从未真正
    // 发起过请求，没有可重放的上下文）。
    messages.value = detail.messages.map((item) => ({
      localId: crypto.randomUUID(),
      id: item.id,
      clientRequestId: crypto.randomUUID(),
      role: item.role,
      text: item.content,
      createdAt: item.createdAt,
      status: 'complete' as const,
      steps: [],
      origin: 'history' as const,
    }))
  }

  /**
   * 丢掉本地缓存的会话列表。切换商家时必须调用——`reset()` 只清当前对话，
   * 会话列表是另一份状态，不清的话抽屉里会留着上一个商家的会话标题。
   */
  function clearConversations(): void {
    conversations.value = []
  }

  async function removeConversation(id: string): Promise<void> {
    const controller = beginTrackedRequest(REMOVE_CONVERSATION_KEY)
    try {
      await deleteConversation(id, controller.signal)
    } finally {
      endTrackedRequest(REMOVE_CONVERSATION_KEY, controller)
    }
    conversations.value = conversations.value.filter((item) => item.id !== id)
    // 删掉的正是当前会话时，回到空会话，避免界面停在已不存在的数据上。
    if (sessionId.value === id) reset()
  }

  return {
    messages,
    sessionId,
    selectedRoundId,
    isEmptyConversation,
    isBusy,
    assistantRounds,
    currentAnswer,
    conversations,
    submitMessage,
    retryMessage,
    cancelMessage,
    selectRound,
    loadConversations,
    loadConversation,
    removeConversation,
    clearConversations,
    reset,
  }
})
