import { ref } from 'vue'
import { defineStore } from 'pinia'

import type { ToolCallView } from '@/api/adapters/chatV2'
import {
  deleteMerchantConversation,
  fetchMerchantConversationHistory,
  fetchMerchantConversations,
  streamMerchantChat,
  submitMerchantFeedback,
  toMerchantTurn,
  type MerchantFeedbackInput,
  type MerchantFeedbackIntent,
  type MerchantFeedbackState,
  type MerchantConversationMessage,
  type MerchantConversationSummary,
  type MerchantTurn,
} from '@/api/adapters/merchantConversations'
import { AppError } from '@/api/errors'

import { registerSessionScopedReset, useAuthStore } from './auth'

export interface OpsMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  toolCalls: ToolCallView[]
  turn?: MerchantTurn
  feedback?: MerchantFeedbackState
  feedbackPending?: boolean
  feedbackError?: string
  feedbackPersisted?: boolean
  feedbackReasonDraft?: string
}

export type DirectoryStatus = 'idle' | 'loading' | 'ready' | 'failed'

function fromHistory(message: MerchantConversationMessage): OpsMessage {
  return {
    id: message.id,
    role: message.role,
    text: message.turn?.envelope.answer ?? message.content,
    toolCalls: message.turn?.toolCalls ?? [],
    turn: message.turn ?? undefined,
    feedback: message.feedback ?? undefined,
    feedbackPersisted: message.feedback
      ? message.feedback.adopted || message.feedback.reaction !== null
      : undefined,
    feedbackReasonDraft: message.feedback?.reason ?? undefined,
  }
}

/** 流式事件与最终响应里的同一个工具调用只保留一行，以最终响应为准。 */
function mergeToolCalls(streamed: ToolCallView[], final: ToolCallView[]): ToolCallView[] {
  const finalIds = new Set(final.map((call) => call.callId))
  return [...streamed.filter((call) => !finalIds.has(call.callId)), ...final]
}

/**
 * v2 运营助手 Store（`n2-conversations-and-feedback` Task 4B）。
 *
 * 当前对话、消息与会话目录都绑定商家会话：换商家（`dropSession`）即全部清空。`generation`
 * 在每次清空时递增，一轮回答或一次打开若在清空之后才返回，就不再写回——否则旧商家的内容
 * 会出现在新商家的界面上（R5）。
 */
export const useOpsChatStore = defineStore('opsChat', () => {
  const messages = ref<OpsMessage[]>([])
  const conversationId = ref<string | null>(null)
  const busy = ref(false)
  const historyTruncated = ref(false)
  /** 前端产生的错误用 i18n 键；后端错误信封的 message 已本地化，放 `errorMessage` 原样展示。 */
  const errorKey = ref<string | null>(null)
  const errorMessage = ref('')
  const conversations = ref<MerchantConversationSummary[]>([])
  const conversationsNextCursor = ref<string | null>(null)
  const directoryStatus = ref<DirectoryStatus>('idle')
  /** 当日简报「下一步动作」预填的问题；只填不发（D18④）。 */
  const pendingInput = ref('')

  let generation = 0
  let latestDirectoryLoad = 0

  function clearError(): void {
    errorKey.value = null
    errorMessage.value = ''
  }

  function setError(error: unknown, fallbackKey: string): void {
    if (error instanceof AppError && error.message) {
      errorKey.value = null
      errorMessage.value = error.message
    } else {
      errorKey.value = fallbackKey
      errorMessage.value = ''
    }
  }

  function resetConversation(): void {
    generation += 1
    messages.value = []
    conversationId.value = null
    historyTruncated.value = false
  }

  registerSessionScopedReset(() => {
    resetConversation()
    clearError()
    busy.value = false
    conversations.value = []
    conversationsNextCursor.value = null
    directoryStatus.value = 'idle'
    latestDirectoryLoad += 1
    pendingInput.value = ''
  })

  function startNew(): void {
    resetConversation()
    clearError()
  }

  async function loadConversations(): Promise<void> {
    const token = ++latestDirectoryLoad
    if (directoryStatus.value !== 'ready') directoryStatus.value = 'loading'
    try {
      const page = await useAuthStore().callWithSessionRetry((sid) =>
        fetchMerchantConversations(sid),
      )
      if (token !== latestDirectoryLoad) return
      conversations.value = page.items
      conversationsNextCursor.value = page.hasMore ? page.nextCursor : null
      directoryStatus.value = 'ready'
    } catch {
      if (token === latestDirectoryLoad) directoryStatus.value = 'failed'
    }
  }

  async function loadMoreConversations(): Promise<void> {
    const cursor = conversationsNextCursor.value
    if (!cursor) return
    const token = latestDirectoryLoad
    try {
      const page = await useAuthStore().callWithSessionRetry((sid) =>
        fetchMerchantConversations(sid, cursor),
      )
      if (token !== latestDirectoryLoad) return
      const known = new Set(conversations.value.map((item) => item.id))
      conversations.value = [
        ...conversations.value,
        ...page.items.filter((item) => !known.has(item.id)),
      ]
      conversationsNextCursor.value = page.hasMore ? page.nextCursor : null
    } catch (error) {
      setError(error, 'opsAssistant.directoryLoadFailed')
    }
  }

  async function openConversation(id: string): Promise<void> {
    const token = ++generation
    clearError()
    try {
      const history = await useAuthStore().callWithSessionRetry((sid) =>
        fetchMerchantConversationHistory(sid, id),
      )
      if (token !== generation) return
      messages.value = history.messages.map(fromHistory)
      conversationId.value = id
      historyTruncated.value = history.truncated
    } catch (error) {
      if (token !== generation) return
      if (error instanceof AppError && error.status === 403) {
        // 不存在、别人的、已删除对外同一种 403：界面也不区分，回到新建态并刷新目录。
        resetConversation()
        errorKey.value = 'opsAssistant.conversationGone'
        errorMessage.value = ''
        await loadConversations()
      } else {
        setError(error, 'opsAssistant.openFailed')
      }
    }
  }

  async function removeConversation(id: string): Promise<void> {
    clearError()
    try {
      await useAuthStore().callWithSessionRetry((sid) => deleteMerchantConversation(sid, id))
    } catch {
      errorKey.value = 'opsAssistant.deleteFailed'
      return
    }
    conversations.value = conversations.value.filter((item) => item.id !== id)
    if (conversationId.value === id) resetConversation()
  }

  function patchLast(update: (message: OpsMessage) => OpsMessage): void {
    const last = messages.value.length - 1
    messages.value = messages.value.map((message, index) =>
      index === last ? update(message) : message,
    )
  }

  async function send(text: string): Promise<void> {
    const message = text.trim()
    if (!message || busy.value) return
    const token = generation
    busy.value = true
    clearError()
    messages.value = [
      ...messages.value,
      { id: crypto.randomUUID(), role: 'user', text: message, toolCalls: [] },
      { id: crypto.randomUUID(), role: 'assistant', text: '', toolCalls: [] },
    ]
    // 同一轮的网络/会话重试复用同一个 client_request_id（后端按它幂等）。
    const input = {
      clientRequestId: crypto.randomUUID(),
      message,
      conversationId: conversationId.value,
    }

    try {
      await useAuthStore().callWithSessionRetry(async (sid) => {
        for await (const event of streamMerchantChat(sid, input)) {
          if (token !== generation) return
          if (event.type === 'tool_call') {
            patchLast((m) => ({
              ...m,
              toolCalls: [...m.toolCalls.filter((c) => c.callId !== event.call.callId), event.call],
            }))
          } else if (event.type === 'tool_result') {
            const result = event.result
            patchLast((m) => ({
              ...m,
              toolCalls: m.toolCalls.map((c) =>
                c.callId === result.callId
                  ? { ...c, status: result.status, summary: result.summary }
                  : c,
              ),
            }))
          } else if (event.type === 'turn_complete') {
            const turn = toMerchantTurn(event.raw)
            conversationId.value = turn.conversationId
            patchLast((m) => ({
              ...m,
              text: turn.envelope.answer,
              turn,
              toolCalls: mergeToolCalls(m.toolCalls, turn.toolCalls),
            }))
          } else if (event.type === 'error') {
            throw AppError.fromErrorResponse(event.error)
          }
        }
      })
    } catch (error) {
      if (token === generation) {
        setError(error, 'opsAssistant.sendFailed')
        // 失败的一轮不留下空白回答气泡。
        messages.value = messages.value.filter(
          (m, index) => !(index === messages.value.length - 1 && !m.text && !m.turn),
        )
      }
    } finally {
      if (token === generation) busy.value = false
    }
    if (token === generation) await loadConversations()
  }

  async function sendFeedback(messageId: string, intent: MerchantFeedbackIntent): Promise<void> {
    const target = messages.value.find((message) => message.id === messageId)
    if (!target?.turn || target.role !== 'assistant' || target.feedbackPending) return
    const token = generation
    const answerId = target.turn.id
    target.feedbackPending = true
    target.feedbackError = undefined
    const input = { ...intent, clientRequestId: crypto.randomUUID() } as MerchantFeedbackInput
    try {
      const feedback = await useAuthStore().callWithSessionRetry((sid) =>
        submitMerchantFeedback(sid, answerId, input),
      )
      if (token !== generation) return
      const current = messages.value.find((message) => message.id === messageId)
      if (!current || current.turn?.id !== answerId) return
      current.feedback = feedback
      current.feedbackPersisted = true
    } catch (error) {
      if (token !== generation) return
      const current = messages.value.find((message) => message.id === messageId)
      if (!current || current.turn?.id !== answerId) return
      current.feedbackError =
        error instanceof AppError && error.message ? error.message : 'feedbackFailed'
    } finally {
      if (token === generation) {
        const current = messages.value.find((message) => message.id === messageId)
        if (current?.turn?.id === answerId) current.feedbackPending = false
      }
    }
  }

  function setFeedbackReason(messageId: string, reason: string): void {
    const target = messages.value.find((message) => message.id === messageId)
    if (target?.turn && !target.feedbackPending) target.feedbackReasonDraft = reason.slice(0, 500)
  }

  function prefill(text: string): void {
    pendingInput.value = text
  }

  function consumePrefill(): string {
    const text = pendingInput.value
    pendingInput.value = ''
    return text
  }

  return {
    messages,
    conversationId,
    busy,
    historyTruncated,
    errorKey,
    errorMessage,
    conversations,
    conversationsNextCursor,
    directoryStatus,
    pendingInput,
    startNew,
    loadConversations,
    loadMoreConversations,
    openConversation,
    removeConversation,
    send,
    sendFeedback,
    setFeedbackReason,
    prefill,
    consumePrefill,
    clearError,
  }
})
