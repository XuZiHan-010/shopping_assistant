import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetSessionForTest, setSession } from '@/api/credentials'
import { ShopContext, type ShopContextValue } from '@/session/ShopContext'
import { apiErrorBody, json, sse, stubBackend, type RecordedCall } from '@/test/fakeBackend'
import { AssistantClient } from '../AssistantClient'

const LIST = 'GET /api/v2/shop/conversations'
const CHAT = 'POST /api/v2/shop/chat'

const summary = (id: string, title: string) => ({
  id, title, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
})

const page = (items: unknown[], nextCursor: string | null = null) => ({
  items, next_cursor: nextCursor, has_more: nextCursor !== null,
})

const answer = (conversationId: string, text: string, over: Record<string, unknown> = {}) => ({
  id: `ans-${conversationId}`, conversation_id: conversationId, answer: text, tool_calls: [],
  created_at: '2026-09-01T00:00:01Z',
  analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
  quality_status: 'PASSED', quality_attempts: 1, degraded: false, degraded_reason: null,
  answer_mode: 'SHOP_GUIDE', suggestions: [], ...over,
})

const chatStream = (conversationId: string, text: string) =>
  sse(`event: turn_complete\ndata: ${JSON.stringify(answer(conversationId, text))}\n\n`)

function contextValue(isBound = true): ShopContextValue {
  return {
    shopSlug: 'borough-100',
    session: { sessionId: 'sess-1', shopSlug: 'borough-100', isBound, expiresAt: '2099-01-01T00:00:00Z' },
    cart: null,
    refreshCart: vi.fn(async () => undefined),
    setCart: vi.fn(),
    bindDemoCustomer: vi.fn(),
    switchIdentity: vi.fn(),
  }
}

function renderAssistant(value: ShopContextValue = contextValue()) {
  const view = render(
    <ShopContext.Provider value={value}>
      <AssistantClient />
    </ShopContext.Provider>,
  )
  return {
    rerenderWith: (next: ShopContextValue) =>
      view.rerender(
        <ShopContext.Provider value={next}>
          <AssistantClient />
        </ShopContext.Provider>,
      ),
  }
}

function directory() {
  return within(screen.getByRole('region', { name: '历史对话' }))
}

async function send(text: string) {
  const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', { name: '向导购助手提问' }), text)
  await user.click(screen.getByRole('button', { name: '发送' }))
}

function chatBodies(calls: RecordedCall[]) {
  return calls.map((call) => call.body as Record<string, unknown>)
}

beforeEach(() => {
  resetSessionForTest()
  setSession({ sessionId: 'sess-1', shopSlug: 'borough-100', isBound: true, expiresAt: '2099-01-01T00:00:00Z' })
})
afterEach(() => vi.unstubAllGlobals())

describe('顾客端会话目录', () => {
  it('列出本主体的对话：会话 ID 只在请求头，列表来自服务端', async () => {
    const backend = stubBackend({ [LIST]: () => json(200, page([summary('c1', '围巾怎么选'), summary('c2', '退货规则')])) })
    renderAssistant()
    expect(await directory().findByRole('button', { name: '围巾怎么选' })).toBeInTheDocument()
    expect(directory().getByRole('button', { name: '退货规则' })).toBeInTheDocument()
    const call = backend.called(LIST)[0]!
    expect(call.headers['X-Session-Id']).toBe('sess-1')
    expect(call.path).not.toContain('sess-1')
  })

  it('没有对话时给出空状态', async () => {
    stubBackend({ [LIST]: () => json(200, page([])) })
    renderAssistant()
    expect(await directory().findByText('还没有历史对话。')).toBeInTheDocument()
  })

  it('目录加载失败：如实提示且不冒充空列表，重试后恢复', async () => {
    const backend = stubBackend({
      [LIST]: () =>
        backend.called(LIST).length === 1
          ? json(503, apiErrorBody('SERVICE_UNAVAILABLE', '服务暂不可用'))
          : json(200, page([summary('c1', '恢复了')])),
    })
    renderAssistant()
    expect(await directory().findByText('历史对话暂时无法加载。')).toBeInTheDocument()
    expect(directory().queryByText('还没有历史对话。')).toBeNull()
    await userEvent.setup().click(directory().getByRole('button', { name: '重试' }))
    expect(await directory().findByRole('button', { name: '恢复了' })).toBeInTheDocument()
  })

  it('有下一页时按 next_cursor 加载更多，追加在末尾', async () => {
    const backend = stubBackend({
      [LIST]: () =>
        json(200, backend.called(LIST).length === 1
          ? page([summary('c1', '第一页')], 'CUR-2')
          : page([summary('c2', '第二页')])),
    })
    renderAssistant()
    await directory().findByRole('button', { name: '第一页' })
    await userEvent.setup().click(directory().getByRole('button', { name: '加载更多' }))
    expect(await directory().findByRole('button', { name: '第二页' })).toBeInTheDocument()
    expect(directory().getByRole('button', { name: '第一页' })).toBeInTheDocument()
    const urls = backend.fetchStub.mock.calls.map(([input]) => String(input))
    expect(urls.some((url) => url.includes('cursor=CUR-2'))).toBe(true)
    expect(directory().queryByRole('button', { name: '加载更多' })).toBeNull()
  })

  it('打开历史对话：显示历史轮次，之后的消息续在该对话里', async () => {
    const backend = stubBackend({
      [LIST]: () => json(200, page([summary('c1', '围巾怎么选')])),
      'GET /api/v2/shop/conversations/c1': () =>
        json(200, {
          conversation: summary('c1', '围巾怎么选'),
          messages: page([
            { id: 'm1', role: 'user', content: '围巾怎么选', created_at: '2026-09-01T00:00:00Z', answer: null },
            {
              id: 'm2', role: 'assistant', content: '羊绒更暖', created_at: '2026-09-01T00:00:01Z',
              answer: answer('c1', '羊绒更暖', { degraded: true, degraded_reason: '知识库暂不可用' }),
            },
          ]),
        }),
      [CHAT]: () => chatStream('c1', '好的'),
    })
    renderAssistant()
    await userEvent.setup().click(await directory().findByRole('button', { name: '围巾怎么选' }))
    expect(await screen.findByText('羊绒更暖')).toBeInTheDocument()
    expect(screen.getAllByText('围巾怎么选').length).toBeGreaterThan(1) // 目录标题 + 历史提问气泡
    // 历史回答同样必须显示降级（R7）。
    expect(screen.getByText(/本次回答已降级：知识库暂不可用/)).toBeInTheDocument()
    expect(directory().getByRole('button', { name: '围巾怎么选' })).toHaveAttribute('aria-current', 'true')

    await send('再来一条')
    await waitFor(() => expect(backend.called(CHAT)).toHaveLength(1))
    expect(chatBodies(backend.called(CHAT))[0]?.conversation_id).toBe('c1')
  })

  it('历史消息超过一页时沿 next_cursor 取完', async () => {
    const backend = stubBackend({
      [LIST]: () => json(200, page([summary('c1', '长对话')])),
      'GET /api/v2/shop/conversations/c1': () =>
        backend.called('GET /api/v2/shop/conversations/c1').length === 1
          ? json(200, {
              conversation: summary('c1', '长对话'),
              messages: page([{ id: 'm1', role: 'user', content: '第一问', created_at: '2026-09-01T00:00:00Z', answer: null }], 'MSG-2'),
            })
          : json(200, {
              conversation: summary('c1', '长对话'),
              messages: page([{ id: 'm2', role: 'user', content: '第二问', created_at: '2026-09-01T00:00:02Z', answer: null }]),
            }),
    })
    renderAssistant()
    await userEvent.setup().click(await directory().findByRole('button', { name: '长对话' }))
    expect(await screen.findByText('第二问')).toBeInTheDocument()
    expect(screen.getByText('第一问')).toBeInTheDocument()
    const urls = backend.fetchStub.mock.calls.map(([input]) => String(input))
    expect(urls.some((url) => url.includes('/conversations/c1') && url.includes('cursor=MSG-2'))).toBe(true)
  })

  it('新建对话：清空当前轮次，下一条消息不带 conversation_id', async () => {
    const backend = stubBackend({
      [LIST]: () => json(200, page([])),
      [CHAT]: () => chatStream('c1', '第一轮回答'),
    })
    renderAssistant()
    await send('第一句')
    expect(await screen.findByText('第一轮回答')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: '新建对话' }))
    expect(screen.queryByText('第一轮回答')).toBeNull()
    await send('新的开始')
    await waitFor(() => expect(backend.called(CHAT)).toHaveLength(2))
    expect(chatBodies(backend.called(CHAT))[1]?.conversation_id).toBeNull()
  })

  it('一轮结束后刷新目录，新对话出现在列表里', async () => {
    let created = false
    stubBackend({
      [LIST]: () => json(200, page(created ? [summary('c1', '第一句')] : [])),
      [CHAT]: () => {
        created = true
        return chatStream('c1', '回答')
      },
    })
    renderAssistant()
    await directory().findByText('还没有历史对话。')
    await send('第一句')
    expect(await directory().findByRole('button', { name: '第一句' })).toBeInTheDocument()
  })

  it('删除后列表移除该对话；删除的不是当前对话时，当前轮次保留', async () => {
    let deleted = false
    const backend = stubBackend({
      [LIST]: () => json(200, page(deleted ? [summary('c1', '当前')] : [summary('c1', '当前'), summary('c2', '旧的')])),
      [CHAT]: () => chatStream('c1', '当前回答'),
      'DELETE /api/v2/shop/conversations/c2': () => {
        deleted = true
        return json(204, null)
      },
    })
    renderAssistant()
    await send('当前')
    expect(await screen.findByText('当前回答')).toBeInTheDocument()

    await userEvent.setup().click(await directory().findByRole('button', { name: '删除对话：旧的' }))
    await waitFor(() => expect(directory().queryByRole('button', { name: '旧的' })).toBeNull())
    expect(backend.called('DELETE /api/v2/shop/conversations/c2')[0]?.headers['X-Session-Id']).toBe('sess-1')
    expect(screen.getByText('当前回答')).toBeInTheDocument()

    await send('继续')
    await waitFor(() => expect(backend.called(CHAT)).toHaveLength(2))
    expect(chatBodies(backend.called(CHAT))[1]?.conversation_id).toBe('c1')
  })

  it('删除当前对话：列表移除，界面回到新建态，下一条消息开启新对话', async () => {
    let deleted = false
    const backend = stubBackend({
      [LIST]: () => json(200, page(deleted ? [] : [summary('c1', '当前')])),
      [CHAT]: () => chatStream(deleted ? 'c9' : 'c1', deleted ? '新对话回答' : '当前回答'),
      'DELETE /api/v2/shop/conversations/c1': () => {
        deleted = true
        return json(204, null)
      },
    })
    renderAssistant()
    await send('当前')
    expect(await screen.findByText('当前回答')).toBeInTheDocument()

    await userEvent.setup().click(await directory().findByRole('button', { name: '删除对话：当前' }))
    await waitFor(() => expect(directory().queryByRole('button', { name: '当前' })).toBeNull())
    expect(screen.queryByText('当前回答')).toBeNull()

    await send('重新开始')
    await waitFor(() => expect(backend.called(CHAT)).toHaveLength(2))
    expect(chatBodies(backend.called(CHAT))[1]?.conversation_id).toBeNull()
  })

  it('身份变化（访客绑定演示顾客）后对话归属随之改变：回到新建态并按新主体刷新目录', async () => {
    const backend = stubBackend({
      [LIST]: () => json(200, page([])),
      [CHAT]: () => chatStream('c1', '访客时的回答'),
    })
    const { rerenderWith } = renderAssistant(contextValue(false))
    await send('随便看看')
    expect(await screen.findByText('访客时的回答')).toBeInTheDocument()
    const listCallsBefore = backend.called(LIST).length

    rerenderWith(contextValue(true))
    await waitFor(() => expect(screen.queryByText('访客时的回答')).toBeNull())
    await waitFor(() => expect(backend.called(LIST).length).toBeGreaterThan(listCallsBefore))

    await send('绑定后再问')
    await waitFor(() => expect(backend.called(CHAT)).toHaveLength(2))
    expect(chatBodies(backend.called(CHAT))[1]?.conversation_id).toBeNull()
  })

  it('删除失败时提示错误，列表不假装已删除', async () => {
    stubBackend({
      [LIST]: () => json(200, page([summary('c1', '留着')])),
      'DELETE /api/v2/shop/conversations/c1': () => json(503, apiErrorBody('SERVICE_UNAVAILABLE', '服务暂不可用')),
    })
    renderAssistant()
    await userEvent.setup().click(await directory().findByRole('button', { name: '删除对话：留着' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('删除失败')
    expect(directory().getByRole('button', { name: '留着' })).toBeInTheDocument()
  })

  it('打开已不可访问的对话（403）：提示不可用、回到新建态并刷新目录', async () => {
    let gone = false
    const backend = stubBackend({
      [LIST]: () => json(200, page(gone ? [] : [summary('c1', '别处已删')])),
      'GET /api/v2/shop/conversations/c1': () => {
        gone = true
        return json(403, apiErrorBody('RESOURCE_FORBIDDEN', '无权访问'))
      },
      [CHAT]: () => chatStream('c9', '新回答'),
    })
    renderAssistant()
    await userEvent.setup().click(await directory().findByRole('button', { name: '别处已删' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('该对话不存在或已删除')
    await waitFor(() => expect(directory().queryByRole('button', { name: '别处已删' })).toBeNull())
    await send('你好')
    await waitFor(() => expect(backend.called(CHAT)).toHaveLength(1))
    expect(chatBodies(backend.called(CHAT))[0]?.conversation_id).toBeNull()
  })
})
