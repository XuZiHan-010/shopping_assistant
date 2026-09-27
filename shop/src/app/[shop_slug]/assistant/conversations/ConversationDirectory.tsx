'use client'

import { useEffect, useRef, useState } from 'react'
import { deleteConversation, listConversations } from '@/api/conversationsApi'
import { formatEventTime } from '@/lib/format'
import type { ConversationSummary } from '@/types/conversation'

interface Props {
  currentId: string | null
  /** 变化即重新拉取第一页：新一轮对话落盘、主体切换、打开失败后都要刷新。 */
  reloadKey: string
  disabled: boolean
  onOpen: (conversationId: string) => void
  onNew: () => void
  onDeleted: (conversationId: string) => void
  onError: (message: string) => void
}

/**
 * 顾客端会话目录（PRD §12.4）：新建、浏览、打开历史对话、删除。
 * 列表只来自服务端 `GET /conversations`（本主体本店，`created_at DESC`），前端不做归属判断。
 */
export function ConversationDirectory({ currentId, reloadKey, disabled, onOpen, onNew, onDeleted, onError }: Props) {
  const [items, setItems] = useState<ConversationSummary[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [phase, setPhase] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  // 只采用最新一次第一页请求的结果：连续触发刷新时，较早返回的旧列表不得覆盖新列表。
  const latestLoad = useRef(0)

  const [retries, setRetries] = useState(0)

  // 刷新时不先切回 loading：保留当前列表直到新结果到达，避免每轮对话后目录闪烁。
  useEffect(() => {
    const token = ++latestLoad.current
    listConversations()
      .then((page) => {
        if (token !== latestLoad.current) return
        setItems(page.items)
        setNextCursor(page.nextCursor)
        setPhase('ready')
      })
      .catch(() => {
        if (token === latestLoad.current) setPhase('failed')
      })
  }, [reloadKey, retries])

  async function loadMore() {
    if (!nextCursor) return
    const token = latestLoad.current
    try {
      const page = await listConversations(nextCursor)
      if (token !== latestLoad.current) return
      setItems((current) => [...current, ...page.items.filter((item) => !current.some((c) => c.id === item.id))])
      setNextCursor(page.nextCursor)
    } catch {
      onError('历史对话加载失败，请稍后重试。')
    }
  }

  async function remove(conversation: ConversationSummary) {
    setPendingDelete(conversation.id)
    try {
      await deleteConversation(conversation.id)
      setItems((current) => current.filter((item) => item.id !== conversation.id))
      onDeleted(conversation.id)
    } catch {
      onError('删除失败，请稍后重试。')
    } finally {
      setPendingDelete(null)
    }
  }

  return (
    <section className="card card-body conversation-directory" aria-label="历史对话">
      <div className="row spread">
        <h2 style={{ margin: 0 }}>历史对话</h2>
        <button className="btn" type="button" disabled={disabled} onClick={onNew}>
          新建对话
        </button>
      </div>

      {phase === 'failed' ? (
        <div className="row">
          <span className="muted">历史对话暂时无法加载。</span>
          <button
            className="btn"
            type="button"
            onClick={() => {
              setPhase('loading')
              setRetries((n) => n + 1)
            }}
          >
            重试
          </button>
        </div>
      ) : phase === 'ready' && items.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>
          还没有历史对话。
        </p>
      ) : (
        <ul className="conversation-list">
          {items.map((item) => (
            <li key={item.id} className="conversation-item">
              <button
                type="button"
                className="conversation-open"
                aria-current={item.id === currentId ? 'true' : undefined}
                disabled={disabled}
                onClick={() => onOpen(item.id)}
              >
                <span className="conversation-title">{item.title}</span>
              </button>
              <span className="muted conversation-time">{formatEventTime(item.createdAt)}</span>
              <button
                type="button"
                className="btn"
                aria-label={`删除对话：${item.title}`}
                disabled={disabled || pendingDelete === item.id}
                onClick={() => void remove(item)}
              >
                删除
              </button>
            </li>
          ))}
        </ul>
      )}

      {nextCursor ? (
        <button className="btn" type="button" disabled={disabled} onClick={() => void loadMore()}>
          加载更多
        </button>
      ) : null}
    </section>
  )
}
