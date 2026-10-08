import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'

import { useAuthStore } from './auth'
import { useOpsChatStore } from './opsChat'

const BASE_URL = 'http://127.0.0.1:8000'
const SESSION = 'sid'.padEnd(43, '0')

type Handler = (body: unknown) => Response

function json(payload: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function errorBody(code: string) {
  return { code, message: code, request_id: 'r', details: [], retryable: false }
}

function answer(conversationId: string, text: string, overrides: Record<string, unknown> = {}) {
  return {
    id: `a-${conversationId}`,
    conversation_id: conversationId,
    answer: text,
    tool_calls: [],
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    quality_status: 'PASSED',
    quality_attempts: 1,
    degraded: false,
    degraded_reason: null,
    created_at: '2026-09-24T00:00:01Z',
    answer_mode: 'MERCHANT_OPS',
    ...overrides,
  }
}

function stream(conversationId: string, text: string): Response {
  return new Response(
    `event: turn_complete\ndata: ${JSON.stringify(answer(conversationId, text))}\n\n`,
    {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    },
  )
}

function summary(id: string, title: string) {
  return { id, title, created_at: '2026-09-24T00:00:00Z', updated_at: '2026-09-24T00:00:00Z' }
}

function page(items: unknown[]) {
  return { items, next_cursor: null, has_more: false }
}

/** 按 `METHOD /path` 路由的 fetch 替身；记录每次调用的请求体。 */
function routeFetch(routes: Record<string, Handler>) {
  const seen: { key: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input))
      const key = `${(init?.method ?? 'GET').toUpperCase()} ${url.pathname}`
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
      seen.push({ key, body })
      const handler = routes[key]
      if (!handler) throw new Error(`未登记的路由：${key}`)
      return handler(body)
    }),
  )
  return {
    bodies: (key: string) =>
      seen.filter((c) => c.key === key).map((c) => c.body as Record<string, unknown>),
    count: (key: string) => seen.filter((c) => c.key === key).length,
  }
}

const LIST = 'GET /api/v2/merchant/conversations'
const CHAT = 'POST /api/v2/merchant/chat'
const FEEDBACK = 'POST /api/v2/merchant/answers/a-c-1/feedback'

/** 改选另一个商家：生产代码里唯一会丢弃旧会话并触发会话作用域重置的入口。 */
function switchMerchant(): void {
  const auth = useAuthStore()
  const other = auth.merchants.find((m) => m.merchantId !== auth.selected?.merchantId)
  if (!other) throw new Error('演示商家少于两个')
  auth.selectByDisplayName(other.displayName)
}

async function openTestSession(): Promise<void> {
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  const auth = useAuthStore()
  await auth.loadMerchants()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValueOnce(
      json(
        {
          session_id: SESSION,
          role: 'MERCHANT',
          expires_at: '2099-01-01T00:00:00Z',
          merchant_display_name: 'Borough商家100',
        },
        201,
      ),
    ),
  )
  await auth.openSession(auth.merchants[0]!)
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('useOpsChatStore', () => {
  it('采纳和赞踩分别提交；完整回执保留另一种状态', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    let adopted = false
    const backend = routeFetch({
      [CHAT]: () => stream('c-1', '回答'),
      [LIST]: () => json(page([])),
      [FEEDBACK]: (body) => {
        const request = body as Record<string, unknown>
        if (request.kind === 'ADOPTION') adopted = request.adopted as boolean
        return json({
          answer_id: 'a-c-1',
          adopted,
          reaction: request.kind === 'REACTION' ? request.reaction : null,
          reason: request.kind === 'REACTION' ? (request.reason ?? null) : null,
          updated_at: '2026-09-24T00:00:02Z',
        })
      },
    })
    await store.send('问题')
    const id = store.messages[1]!.id
    await store.sendFeedback(id, { kind: 'ADOPTION', adopted: true })
    await store.sendFeedback(id, { kind: 'REACTION', reaction: 'LIKE', reason: '有帮助' })
    expect(backend.bodies(FEEDBACK)).toEqual([
      { client_request_id: expect.any(String), kind: 'ADOPTION', adopted: true },
      {
        client_request_id: expect.any(String),
        kind: 'REACTION',
        reaction: 'LIKE',
        reason: '有帮助',
      },
    ])
    expect(store.messages[1]!.feedback).toEqual({
      adopted: true,
      reaction: 'LIKE',
      reason: '有帮助',
    })
  })

  it('历史回答可反馈；切换商家后迟到回执不得写回', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    routeFetch({
      'GET /api/v2/merchant/conversations/c-1': () =>
        json({
          conversation: summary('c-1', '旧对话'),
          messages: page([
            {
              id: 'm-1',
              role: 'assistant',
              content: '旧回答',
              created_at: '2026-09-24T00:00:01Z',
              answer: answer('c-1', '旧回答'),
              feedback: { adopted: false, reaction: null, reason: null },
            },
          ]),
        }),
      [FEEDBACK]: () =>
        new Response(
          new ReadableStream({
            async start(controller) {
              await gate
              controller.enqueue(
                new TextEncoder().encode(
                  JSON.stringify({
                    answer_id: 'a-c-1',
                    adopted: true,
                    reaction: null,
                    reason: null,
                    updated_at: '2026-09-24T00:00:02Z',
                  }),
                ),
              )
              controller.close()
            },
          }),
          { headers: { 'content-type': 'application/json' } },
        ),
    })
    await store.openConversation('c-1')
    const pending = store.sendFeedback('m-1', { kind: 'ADOPTION', adopted: true })
    await vi.waitFor(() => expect(store.messages[0]!.feedbackPending).toBe(true))
    switchMerchant()
    release()
    await pending
    expect(store.messages).toEqual([])
  })
  it('新对话不带 conversation_id；回答后记住它，续聊带上；每轮结束刷新目录', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    const backend = routeFetch({
      [CHAT]: () => stream('c-1', '有 1 个商品低库存。'),
      [LIST]: () => json(page([summary('c-1', '库存怎么样')])),
    })

    await store.send('库存怎么样')
    expect(store.conversationId).toBe('c-1')
    expect(store.messages.map((m) => [m.role, m.text])).toEqual([
      ['user', '库存怎么样'],
      ['assistant', '有 1 个商品低库存。'],
    ])
    expect(store.conversations.map((c) => c.id)).toEqual(['c-1'])

    await store.send('再看看')
    const bodies = backend.bodies(CHAT)
    expect(bodies[0]!.conversation_id).toBeNull()
    expect(bodies[1]!.conversation_id).toBe('c-1')
    expect(bodies[0]!.client_request_id).not.toBe(bodies[1]!.client_request_id)
    expect(JSON.stringify(bodies)).not.toMatch(/merchant_id|session_id/)
  })

  it('打开历史对话：载入历史轮次，之后续在该对话里', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    const backend = routeFetch({
      'GET /api/v2/merchant/conversations/c-7': () =>
        json({
          conversation: summary('c-7', '旧的'),
          messages: page([
            {
              id: 'm-1',
              role: 'user',
              content: '旧问题',
              created_at: '2026-09-24T00:00:00Z',
              answer: null,
              feedback: null,
            },
            {
              id: 'm-2',
              role: 'assistant',
              content: '旧回答',
              created_at: '2026-09-24T00:00:01Z',
              answer: answer('c-7', '旧回答'),
              feedback: { adopted: true, reaction: 'LIKE', reason: '有帮助' },
            },
          ]),
        }),
      [CHAT]: () => stream('c-7', '新回答'),
      [LIST]: () => json(page([summary('c-7', '旧的')])),
    })

    await store.openConversation('c-7')
    expect(store.conversationId).toBe('c-7')
    expect(store.messages.map((m) => m.text)).toEqual(['旧问题', '旧回答'])
    expect(store.messages[1]!.turn?.envelope.answer).toBe('旧回答')
    expect(store.messages[1]!.feedback).toEqual({
      adopted: true,
      reaction: 'LIKE',
      reason: '有帮助',
    })
    expect(store.messages[1]!.feedbackPersisted).toBe(true)

    await store.send('接着问')
    expect(backend.bodies(CHAT)[0]!.conversation_id).toBe('c-7')
  })

  it('删除当前对话：目录移除，回到新建态；删除别的对话不影响当前', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    const backend = routeFetch({
      [CHAT]: () => stream('c-1', '当前回答'),
      [LIST]: () => json(page([summary('c-1', '当前'), summary('c-2', '别的')])),
      'DELETE /api/v2/merchant/conversations/c-2': () => json(null, 204),
      'DELETE /api/v2/merchant/conversations/c-1': () => json(null, 204),
    })
    await store.send('当前')

    await store.removeConversation('c-2')
    expect(store.conversations.map((c) => c.id)).toEqual(['c-1'])
    expect(store.conversationId).toBe('c-1')
    expect(store.messages).toHaveLength(2)

    await store.removeConversation('c-1')
    expect(store.conversations).toEqual([])
    expect(store.conversationId).toBeNull()
    expect(store.messages).toEqual([])
    expect(backend.count('DELETE /api/v2/merchant/conversations/c-1')).toBe(1)
  })

  it('删除失败：如实报错，目录不假装已删除', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    routeFetch({
      [LIST]: () => json(page([summary('c-1', '留着')])),
      'DELETE /api/v2/merchant/conversations/c-1': () =>
        json(errorBody('SERVICE_UNAVAILABLE'), 503),
    })
    await store.loadConversations()
    await store.removeConversation('c-1')
    expect(store.conversations.map((c) => c.id)).toEqual(['c-1'])
    expect(store.errorKey).toBe('opsAssistant.deleteFailed')
  })

  it('打开已不可访问的对话（403）：回到新建态、提示并刷新目录', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    let gone = false
    routeFetch({
      'GET /api/v2/merchant/conversations/c-9': () => {
        gone = true
        return json(errorBody('RESOURCE_FORBIDDEN'), 403)
      },
      [LIST]: () => json(page(gone ? [] : [summary('c-9', '别处已删')])),
    })
    await store.loadConversations()
    await store.openConversation('c-9')
    expect(store.conversationId).toBeNull()
    expect(store.errorKey).toBe('opsAssistant.conversationGone')
    expect(store.conversations).toEqual([])
  })

  it('Chat 失败：显示错误，不留下空白回答', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    routeFetch({
      [CHAT]: () => json(errorBody('RATE_LIMITED'), 429),
      [LIST]: () => json(page([])),
    })
    await store.send('你好')
    expect(store.messages.map((m) => m.role)).toEqual(['user'])
    // 后端错误信封的 message 已按 Accept-Language 本地化，原样展示。
    expect(store.errorMessage).toBe('RATE_LIMITED')
    expect(store.busy).toBe(false)
  })

  it('换商家发生在一轮回答途中：迟到的回答不写回已清空的对话', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    routeFetch({
      [CHAT]: () =>
        new Response(
          new ReadableStream({
            async start(controller) {
              await gate
              controller.enqueue(
                new TextEncoder().encode(
                  `event: turn_complete\ndata: ${JSON.stringify(answer('c-old', '旧商家的回答'))}\n\n`,
                ),
              )
              controller.close()
            },
          }),
          { status: 200, headers: { 'content-type': 'text/event-stream' } },
        ),
      [LIST]: () => json(page([])),
    })
    const pending = store.send('问题')
    await vi.waitFor(() => expect(store.busy).toBe(true))
    switchMerchant()
    release()
    await pending
    expect(store.messages).toEqual([])
    expect(store.conversationId).toBeNull()
  })

  it('换商家（会话作用域重置）：对话、目录与预填全部清空', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    routeFetch({
      [CHAT]: () => stream('c-1', '回答'),
      [LIST]: () => json(page([summary('c-1', '问题')])),
      'DELETE /api/v2/merchant/sessions/current': () => json(null, 204),
    })
    await store.send('问题')
    store.prefill('给「测试商品」起草补货草稿')

    switchMerchant()

    expect(store.messages).toEqual([])
    expect(store.conversationId).toBeNull()
    expect(store.conversations).toEqual([])
    expect(store.pendingInput).toBe('')
  })

  it('预填只写入待填文本，不发送任何请求', async () => {
    await openTestSession()
    const store = useOpsChatStore()
    const backend = routeFetch({})
    store.prefill('给「测试商品」起草补货草稿')
    expect(store.pendingInput).toBe('给「测试商品」起草补货草稿')
    expect(store.consumePrefill()).toBe('给「测试商品」起草补货草稿')
    expect(store.pendingInput).toBe('')
    expect(backend.count(CHAT)).toBe(0)
  })
})
