import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { submitChat } from '@/api/chat'
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

  async function submitMessage(text: string): Promise<void> {
    const content = text.trim()
    if (!content) return

    const clientRequestId = crypto.randomUUID()
    const user = newMessage('user', content, clientRequestId, 'complete')
    const assistant = newMessage('assistant', '', clientRequestId, 'pending')
    messages.value.push(user, assistant)

    await runRound(assistant, content)
  }

  const isBusy = computed(() =>
    messages.value.some(
      (message) => message.status === 'pending' || message.status === 'streaming',
    ),
  )

  function cancelMessage(localId: string): void {
    // 真正中断底层流，不只是 UI 上隐藏——否则后端会继续跑完并计费。
    controllers.get(localId)?.abort()
  }

  async function retryMessage(localId: string): Promise<void> {
    const assistant = messages.value.find((message) => message.localId === localId)
    if (!assistant || assistant.role !== 'assistant') return

    const questionIndex = messages.value.findIndex((message) => message.localId === localId) - 1
    const question = messages.value[questionIndex]
    if (!question) return

    // 复用原 clientRequestId：后端据此可能直接返回已完成结果，避免重复计费（§5.9）。
    assistant.status = 'pending'
    assistant.errorMessage = undefined
    assistant.steps = []

    await runRound(assistant, question.text)
  }

  return {
    messages,
    sessionId,
    selectedRoundId,
    isEmptyConversation,
    isBusy,
    assistantRounds,
    currentAnswer,
    submitMessage,
    retryMessage,
    cancelMessage,
    selectRound,
    reset,
  }
})
