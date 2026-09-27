'use client'

import Link from 'next/link'
import { useRef, useState, type FormEvent } from 'react'
import { streamShopChat } from '@/api/chat'
import { getConversationHistory, MAX_HISTORY_MESSAGES } from '@/api/conversationsApi'
import { ApiError, NetworkError } from '@/api/errors'
import { ChatStreamInterruptedError } from '@/api/sse'
import { formatPrice } from '@/lib/format'
import { useShop } from '@/session/ShopContext'
import type { ChatTurn, ToolCall } from '@/types/chat'
import type { ConversationMessage } from '@/types/conversation'
import { ConversationDirectory } from './conversations/ConversationDirectory'

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  toolCalls: ToolCall[]
  turn?: ChatTurn
}

function mergeToolCalls(streamed: ToolCall[], final: ToolCall[]): ToolCall[] {
  const finalIds = new Set(final.map((call) => call.callId))
  return [...streamed.filter((call) => !finalIds.has(call.callId)), ...final]
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof ChatStreamInterruptedError) return '回答意外中断，请重试。'
  if (error instanceof NetworkError) return '网络异常，请重试。'
  return '导购助手暂时不可用，请稍后重试。'
}

function fromHistory(message: ConversationMessage): Message {
  return {
    id: message.id,
    role: message.role,
    text: message.turn?.answer ?? message.content,
    toolCalls: message.turn?.toolCalls ?? [],
    turn: message.turn ?? undefined,
  }
}

/**
 * 导购 Agent（C2 最小集）。
 * - 工具行只显示名称、状态与摘要；参数与结果不会出现在事件里，也不会渲染。
 * - 购物车以服务端 `GET /cart` 为准：每轮结束后刷新，不从回答文本里解析。
 * - 降级原因随回答展示（R7），不把降级包装成正常回答。
 */
export function AssistantClient() {
  const { shopSlug, cart, refreshCart, session } = useShop()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [historyTruncated, setHistoryTruncated] = useState(false)
  const [directoryVersion, setDirectoryVersion] = useState(0)
  const latestOpen = useRef(0)

  // 对话归属跟主体走（访客按认证会话、已绑定按 buyer_key）：主体一变，原对话就不再属于当前身份，
  // 续聊会被服务端拒绝。所以主体变化时回到新建态，目录按新主体重新拉取。
  const principalKey = session ? `${session.sessionId}:${session.isBound ? 'bound' : 'guest'}` : 'none'
  const [principal, setPrincipal] = useState(principalKey)
  if (principal !== principalKey) {
    setPrincipal(principalKey)
    setMessages([])
    setConversationId(null)
    setHistoryTruncated(false)
    setError(null)
  }

  function resetToNew() {
    latestOpen.current += 1
    setMessages([])
    setConversationId(null)
    setHistoryTruncated(false)
    setError(null)
  }

  async function openConversation(id: string) {
    const token = ++latestOpen.current
    setError(null)
    try {
      const history = await getConversationHistory(id)
      if (token !== latestOpen.current) return
      setMessages(history.messages.map(fromHistory))
      setConversationId(id)
      setHistoryTruncated(history.truncated)
    } catch (caught) {
      if (token !== latestOpen.current) return
      if (caught instanceof ApiError && caught.status === 403) {
        // 不存在、别人的、已删除对外同一种 403：界面也不区分，回到新建态并刷新目录。
        resetToNew()
        setError('该对话不存在或已删除。')
        setDirectoryVersion((v) => v + 1)
      } else {
        setError(describeError(caught))
      }
    }
  }

  function onDeleted(id: string) {
    if (id === conversationId) resetToNew()
  }

  function patchLast(update: (message: Message) => Message) {
    setMessages((current) => current.map((m, i) => (i === current.length - 1 ? update(m) : m)))
  }

  async function send(text: string) {
    const message = text.trim()
    if (!message || busy) return
    setBusy(true)
    setError(null)
    setInput('')
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', text: message, toolCalls: [] },
      { id: crypto.randomUUID(), role: 'assistant', text: '', toolCalls: [] },
    ])

    try {
      for await (const event of streamShopChat({
        clientRequestId: crypto.randomUUID(),
        message,
        conversationId,
      })) {
        if (event.type === 'tool_call' || event.type === 'tool_result') {
          patchLast((m) => ({
            ...m,
            toolCalls: [...m.toolCalls.filter((c) => c.callId !== event.call.callId), event.call],
          }))
        } else if (event.type === 'turn_complete') {
          setConversationId(event.response.conversationId)
          // 最终响应里的 tool_calls 是权威列表：没有逐条流式事件时它是唯一来源，
          // 有流式事件时按 call_id 合并，同一个调用只显示一行。
          patchLast((m) => ({
            ...m,
            text: event.response.answer,
            turn: event.response,
            toolCalls: mergeToolCalls(m.toolCalls, event.response.toolCalls),
          }))
        } else {
          throw event.error
        }
      }
    } catch (caught) {
      setError(describeError(caught))
      // 失败的一轮不留下空白回答气泡。
      setMessages((current) => current.filter((m, i) => !(i === current.length - 1 && !m.text && !m.turn)))
    } finally {
      setBusy(false)
      // 新对话或新一轮都会改变目录（新条目、标题），以服务端为准重新拉取。
      setDirectoryVersion((v) => v + 1)
      // 无论成败都以服务端为准刷新购物车：Agent 可能在失败前已经加购。
      await refreshCart().catch(() => undefined)
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void send(input)
  }

  const lastTurn = [...messages].reverse().find((m) => m.turn)?.turn

  return (
    <div className="assistant-layout">
      {session ? (
        <ConversationDirectory
          currentId={conversationId}
          reloadKey={`${principalKey}:${directoryVersion}`}
          disabled={busy}
          onOpen={(id) => void openConversation(id)}
          onNew={resetToNew}
          onDeleted={onDeleted}
          onError={setError}
        />
      ) : null}
    <div className="stack assistant-main">
      <h1>导购助手</h1>
      <p className="muted">
        助手只能在本店范围内查商品、比较和加购；提交订单与支付需要你在页面上确认。
      </p>

      {historyTruncated ? (
        <p className="muted" role="note">
          这段对话较长，仅显示前 {MAX_HISTORY_MESSAGES} 条消息。
        </p>
      ) : null}

      <div className="chat-log" aria-live="polite">
        {messages.map((message) => (
          <div key={message.id} className={`bubble ${message.role === 'user' ? 'bubble-user' : ''}`}>
            {message.toolCalls.map((call) => (
              <div key={call.callId} className="tool-row">
                {call.toolName} · {call.summary}
              </div>
            ))}
            {message.text ? <div>{message.text}</div> : null}
            {message.turn?.degraded ? (
              <p className="notice" role="note" style={{ margin: '8px 0 0' }}>
                本次回答已降级：{message.turn.degradedReason ?? '部分能力暂不可用'}
              </p>
            ) : null}
            {message.turn?.analysisSources
              .filter((source) => source.degraded && source.degradedReason)
              .map((source) => (
                <p key={source.source} className="muted" style={{ margin: '4px 0 0' }}>
                  来源 {source.source} 降级：{source.degradedReason}
                </p>
              ))}
          </div>
        ))}
      </div>

      {lastTurn && lastTurn.suggestions.length > 0 ? (
        <div className="row">
          {lastTurn.suggestions.map((suggestion) => (
            <button key={suggestion} className="btn" disabled={busy} onClick={() => void send(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}

      {error ? (
        <div className="notice notice-error" role="alert">
          {error}
        </div>
      ) : null}

      <form className="row" onSubmit={onSubmit}>
        <input
          aria-label="向导购助手提问"
          style={{ flex: 1, minHeight: 'var(--control-height)' }}
          value={input}
          disabled={!session}
          onChange={(event) => setInput(event.target.value)}
          placeholder="例如：帮我比较两款围巾，再加一条到购物车"
        />
        <button className="btn btn-primary" type="submit" disabled={busy || !session || !input.trim()}>
          发送
        </button>
      </form>

      <section className="card card-body" aria-label="结账摘要">
        <h2>结账摘要</h2>
        {cart && cart.items.length > 0 ? (
          <>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {cart.items.map((item) => (
                <li key={item.productId} className="row spread">
                  <span>
                    {item.name} × {item.quantity}
                  </span>
                  <span>{formatPrice(item.lineTotalCents)}</span>
                </li>
              ))}
            </ul>
            <div className="row spread">
              <span>小计</span>
              <span className="price">{formatPrice(cart.subtotalCents)}</span>
            </div>
          </>
        ) : (
          <p className="muted">购物车还是空的。</p>
        )}
        <p className="muted" style={{ margin: 0 }}>
          摘要仅供展示，以结账页计算为准。
        </p>
        <Link className="btn btn-primary" href={`/${shopSlug}/cart`} style={{ display: 'inline-grid', alignItems: 'center' }}>
          去结账
        </Link>
      </section>
    </div>
    </div>
  )
}
