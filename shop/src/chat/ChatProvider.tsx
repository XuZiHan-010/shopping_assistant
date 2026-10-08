'use client'

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { streamShopChat } from '@/api/chat'
import { getConversationHistory } from '@/api/conversationsApi'
import { ApiError, NetworkError } from '@/api/errors'
import { ChatStreamInterruptedError } from '@/api/sse'
import { useLocale } from '@/i18n/LocaleProvider'
import { useShop } from '@/session/ShopContext'
import type { ChatTurn, ToolCall } from '@/types/chat'

export interface ChatMessage { id: string; role: 'user' | 'assistant'; text: string; toolCalls: ToolCall[]; turn?: ChatTurn }
export interface TurnRecord { question: string; turn: ChatTurn; elapsedMs: number }
interface ChatState {
  messages: ChatMessage[]; busy: boolean; error: string | null; conversationId: string | null
  historyTruncated: boolean; turns: TurnRecord[]; directoryVersion: number
  send: (text: string) => Promise<void>; openConversation: (id: string) => Promise<void>
  resetToNew: () => void; onDeleted: (id: string) => void; setError: (error: string | null) => void
}
const Context = createContext<ChatState | null>(null)
export function useChat(): ChatState {
  const state = useContext(Context)
  if (!state) throw new Error('useChat requires ChatProvider')
  return state
}

/** 主体变更时销毁整份状态；旧流、旧历史请求均失去写回权。布局导航不会销毁此 Provider。 */
export function ChatProvider({ children }: { children: ReactNode }) {
  const { session, shopSlug } = useShop()
  const principal = `${shopSlug}:${session?.sessionId ?? ''}:${session?.isBound ?? false}`
  return <PrincipalChat key={principal}>{children}</PrincipalChat>
}

function PrincipalChat({ children }: { children: ReactNode }) {
  const { refreshCart } = useShop()
  const { t } = useLocale()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [historyTruncated, setHistoryTruncated] = useState(false)
  const [turns, setTurns] = useState<TurnRecord[]>([])
  const [directoryVersion, setDirectoryVersion] = useState(0)
  const generation = useRef(0)
  const locked = useRef(false)
  useEffect(() => () => { generation.current += 1 }, [])

  function describeError(caught: unknown): string {
    if (caught instanceof ApiError) return caught.message
    if (caught instanceof ChatStreamInterruptedError) return t('chat.interrupted')
    if (caught instanceof NetworkError) return t('chat.network')
    return t('chat.unavailable')
  }
  function resetToNew() {
    generation.current += 1
    locked.current = false
    setBusy(false); setMessages([]); setTurns([]); setConversationId(null)
    setHistoryTruncated(false); setError(null); setDirectoryVersion(v => v + 1)
  }
  async function openConversation(id: string) {
    if (locked.current) return
    const token = ++generation.current
    setError(null)
    try {
      const history = await getConversationHistory(id)
      if (token !== generation.current) return
      setMessages(history.messages.map(message => ({ id: message.id, role: message.role, text: message.turn?.answer ?? message.content, toolCalls: message.turn?.toolCalls ?? [], turn: message.turn ?? undefined })))
      setConversationId(id); setHistoryTruncated(history.truncated); setTurns([])
    } catch (caught) {
      if (token !== generation.current) return
      if (caught instanceof ApiError && caught.status === 403) { resetToNew(); setError(t('chat.historyMissing')) }
      else setError(describeError(caught))
    }
  }
  async function send(text: string) {
    const message = text.trim()
    if (!message || locked.current) return
    locked.current = true
    const token = ++generation.current
    const started = performance.now()
    const answerId = crypto.randomUUID()
    setBusy(true); setError(null)
    setMessages(current => [...current, { id: crypto.randomUUID(), role: 'user', text: message, toolCalls: [] }, { id: answerId, role: 'assistant', text: '', toolCalls: [] }])
    const patch = (update: (m: ChatMessage) => ChatMessage) => setMessages(current => current.map(m => m.id === answerId ? update(m) : m))
    try {
      for await (const event of streamShopChat({ clientRequestId: crypto.randomUUID(), message, conversationId })) {
        if (token !== generation.current) return
        if (event.type === 'tool_call' || event.type === 'tool_result') {
          patch(m => ({ ...m, toolCalls: [...m.toolCalls.filter(c => c.callId !== event.call.callId), event.call] }))
        } else if (event.type === 'turn_complete') {
          setConversationId(event.response.conversationId)
          patch(m => ({ ...m, text: event.response.answer, turn: event.response, toolCalls: [...m.toolCalls.filter(c => !event.response.toolCalls.some(f => f.callId === c.callId)), ...event.response.toolCalls] }))
          setTurns(current => [...current, { question: message, turn: event.response, elapsedMs: Math.max(0, performance.now() - started) }])
        } else throw event.error
      }
    } catch (caught) {
      if (token !== generation.current) return
      setError(describeError(caught))
      setMessages(current => current.filter(m => m.id !== answerId || m.text || m.turn))
    } finally {
      if (token === generation.current) {
        locked.current = false; setBusy(false); setDirectoryVersion(v => v + 1)
        await refreshCart().catch(() => undefined)
      }
    }
  }
  return <Context.Provider value={{ messages, busy, error, conversationId, historyTruncated, turns, directoryVersion, send, openConversation, resetToNew, onDeleted: id => { if (id === conversationId) resetToNew() }, setError }}>{children}</Context.Provider>
}
