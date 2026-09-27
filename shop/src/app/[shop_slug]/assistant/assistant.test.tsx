import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetSessionForTest, setSession } from '@/api/credentials'
import { ShopContext, type ShopContextValue } from '@/session/ShopContext'
import { apiErrorBody, json, sse, stubBackend } from '@/test/fakeBackend'
import type { Cart } from '@/types/shop'
import { AssistantClient } from './AssistantClient'

const turn = (over: Record<string, unknown> = {}) =>
  JSON.stringify({
    id: 'a1', conversation_id: 'conv-1', answer: '已把羊绒围巾加入购物车（共 3 件）', tool_calls: [],
    created_at: '2026-09-01T00:00:00Z',
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    quality_status: 'PASSED', quality_attempts: 1, degraded: false, degraded_reason: null,
    answer_mode: 'SHOP_GUIDE', suggestions: [], ...over,
  })

const happyStream = (over: Record<string, unknown> = {}) =>
  sse(
    'event: tool_call\ndata: {"tool_name":"set_cart_item","call_id":"c1","status":"STARTED","summary":"正在处理","arguments":{"product_id":"SECRET-ARG"}}\n\n' +
      'event: tool_result\ndata: {"tool_name":"set_cart_item","call_id":"c1","status":"SUCCEEDED","summary":"处理完成"}\n\n' +
      `event: turn_complete\ndata: ${turn(over)}\n\n`,
  )

function renderAssistant(cart: Cart | null = null) {
  const refreshCart = vi.fn(async () => undefined)
  const value: ShopContextValue = {
    shopSlug: 'borough-100',
    session: { sessionId: 'sess-1', shopSlug: 'borough-100', isBound: true, expiresAt: '2099-01-01T00:00:00Z' },
    cart,
    refreshCart,
    setCart: vi.fn(),
    bindDemoCustomer: vi.fn(),
    switchIdentity: vi.fn(),
  }
  render(
    <ShopContext.Provider value={value}>
      <AssistantClient />
    </ShopContext.Provider>,
  )
  return { refreshCart }
}

async function send(text: string) {
  const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', { name: '向导购助手提问' }), text)
  await user.click(screen.getByRole('button', { name: '发送' }))
}

beforeEach(() => {
  resetSessionForTest()
  setSession({ sessionId: 'sess-1', shopSlug: 'borough-100', isBound: true, expiresAt: '2099-01-01T00:00:00Z' })
})
afterEach(() => vi.unstubAllGlobals())

describe('C2 导购 Agent', () => {
  it('购物车角标来自服务端 GET /cart，而不是解析回答文本', async () => {
    stubBackend({ 'POST /api/v2/shop/chat': () => happyStream() })
    const { refreshCart } = renderAssistant()
    await send('帮我加一个')
    await waitFor(() => expect(refreshCart).toHaveBeenCalled())
    expect(await screen.findByText(/已把羊绒围巾加入购物车/)).toBeInTheDocument()
  })

  it('工具行只显示名称与状态摘要，不显示参数或结果', async () => {
    stubBackend({ 'POST /api/v2/shop/chat': () => happyStream() })
    renderAssistant()
    await send('帮我加一个')
    expect(await screen.findByText(/set_cart_item/)).toBeInTheDocument()
    expect(screen.getByText(/处理完成/)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('SECRET-ARG')
  })

  it('后端只在 turn_complete 里给出 tool_calls（没有逐条流式事件）时，工具行仍然显示', async () => {
    stubBackend({
      'POST /api/v2/shop/chat': () =>
        sse(
          `event: turn_complete
data: ${turn({
            tool_calls: [{ tool_name: 'search_products', call_id: 'c1', status: 'SUCCEEDED', summary: '处理完成' }],
          })}

`,
        ),
    })
    renderAssistant()
    await send('找围巾')
    expect(await screen.findByText(/search_products · 处理完成/)).toBeInTheDocument()
  })

  it('流式事件与最终响应里的同一个工具调用只显示一行', async () => {
    stubBackend({
      'POST /api/v2/shop/chat': () =>
        happyStream({
          tool_calls: [{ tool_name: 'set_cart_item', call_id: 'c1', status: 'SUCCEEDED', summary: '处理完成' }],
        }),
    })
    renderAssistant()
    await send('帮我加一个')
    await screen.findByText(/已把羊绒围巾加入购物车/)
    expect(screen.getAllByText(/set_cart_item/)).toHaveLength(1)
  })

  it('请求头带会话 ID，请求体不带会话 ID 或 merchant_id', async () => {
    const backend = stubBackend({ 'POST /api/v2/shop/chat': () => happyStream() })
    renderAssistant()
    await send('你好')
    await waitFor(() => expect(backend.called('POST /api/v2/shop/chat')).toHaveLength(1))
    const call = backend.called('POST /api/v2/shop/chat')[0]!
    expect(call.headers['X-Session-Id']).toBe('sess-1')
    expect(call.headers['Accept']).toBe('text/event-stream')
    expect(JSON.stringify(call.body)).not.toMatch(/sess-1|merchant_id|buyer_key/)
  })

  it('同一对话内后续消息沿用 conversation_id', async () => {
    const backend = stubBackend({ 'POST /api/v2/shop/chat': () => happyStream() })
    renderAssistant()
    await send('第一句')
    await screen.findByText(/已把羊绒围巾加入购物车/)
    await send('第二句')
    await waitFor(() => expect(backend.called('POST /api/v2/shop/chat')).toHaveLength(2))
    const bodies = backend.called('POST /api/v2/shop/chat').map((c) => c.body as Record<string, unknown>)
    expect(bodies[0]?.conversation_id).toBeNull()
    expect(bodies[1]?.conversation_id).toBe('conv-1')
    expect(bodies[0]?.client_request_id).not.toBe(bodies[1]?.client_request_id)
  })

  it('降级必须对用户可见（R7）：显示降级原因，不包装成正常回答', async () => {
    stubBackend({
      'POST /api/v2/shop/chat': () =>
        happyStream({
          degraded: true,
          degraded_reason: '知识库暂不可用，本次仅依据商品数据回答',
          analysis_sources: [{ source: 'KNOWLEDGE', degraded: true, degraded_reason: '知识库暂不可用' }],
        }),
    })
    renderAssistant()
    await send('退货规则？')
    expect(await screen.findByText(/知识库暂不可用，本次仅依据商品数据回答/)).toBeInTheDocument()
  })

  it('请求被拒绝时显示错误，不留下空白回答', async () => {
    stubBackend({ 'POST /api/v2/shop/chat': () => json(429, apiErrorBody('RATE_LIMITED', '请求过于频繁')) })
    renderAssistant()
    await send('你好')
    expect(await screen.findByRole('alert')).toHaveTextContent(/请求过于频繁/)
  })

  it('结账摘要仅供展示，并标注以结账页计算为准', () => {
    renderAssistant({
      subtotalCents: 25900,
      items: [
        { productId: 'p1', name: '羊绒围巾', imageUrl: null, quantity: 1, unitPriceCents: 25900, lineTotalCents: 25900, stockBand: 'IN_STOCK' },
      ],
    })
    expect(screen.getByText(/以结账页计算为准/)).toBeInTheDocument()
    expect(screen.getAllByText('¥259.00')).toHaveLength(2) // 行金额与小计，均为后端值
  })
})
