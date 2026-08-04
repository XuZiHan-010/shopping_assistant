import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  deleteConversation,
  getConversation,
  listConversations,
  submitChat,
  type ConversationSummaryView,
} from '@/api/chat'
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
  }
}

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
    } catch (error) {
      const name = (error as Error).name
      assistant.status = name === 'AbortError' ? 'cancelled' : 'error'
      assistant.errorMessage = name === 'AbortError' ? '已取消本次回答。' : (error as Error).message
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
    assistant.errorMessage = undefined
    assistant.steps = []

    await runRound(assistant, question.text)
    return true
  }

  const conversations = ref<ConversationSummaryView[]>([])

  async function loadConversations(): Promise<void> {
    conversations.value = await listConversations(new AbortController().signal)
  }

  async function loadConversation(id: string): Promise<void> {
    const detail = await getConversation(id, new AbortController().signal)

    // 顺序要紧：reset() 会清空 sessionId，放到赋值之后会把刚设好的会话 ID 抹掉。
    reset()
    sessionId.value = detail.id
    // 历史消息没有流式过程，直接落到终态；answer 留空，侧栏因此显示空状态而不是
    // 上一轮的残留——重新提问才会有完整回答载荷。
    messages.value = detail.messages.map((item) => ({
      localId: crypto.randomUUID(),
      id: item.id,
      clientRequestId: crypto.randomUUID(),
      role: item.role,
      text: item.content,
      createdAt: item.createdAt,
      status: 'complete' as const,
      steps: [],
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
    await deleteConversation(id, new AbortController().signal)
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
