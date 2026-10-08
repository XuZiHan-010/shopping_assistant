import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ShopContext, type ShopContextValue } from '@/session/ShopContext'
import { ChatProvider, useChat } from './ChatProvider'

const stream = vi.hoisted(() => vi.fn())
const history = vi.hoisted(() => vi.fn())
vi.mock('@/api/chat', () => ({ streamShopChat: stream }))
vi.mock('@/api/conversationsApi', () => ({ getConversationHistory: history }))
function Probe() {
  const chat = useChat()
  return <><button onClick={() => void chat.send('hello')}>send</button><button onClick={() => void chat.send('next')}>next</button><button onClick={() => void chat.openConversation('c1')}>open</button><button onClick={chat.resetToNew}>new</button><span data-testid="messages">{chat.messages.map(m => m.text).join('|')}</span><span data-testid="conversation">{chat.conversationId}</span><span data-testid="error">{chat.error}</span><span data-testid="calls">{chat.messages.flatMap(m => m.toolCalls).map(c => c.callId).join('|')}</span><span data-testid="turns">{chat.turns.length}</span></>
}
const base: ShopContextValue = {
  shopSlug: 'borough-100', session: { sessionId: 's', shopSlug: 'borough-100', isBound: false, expiresAt: '2099-01-01' },
  view: 'assistant', panel: null, productId: null, openPanel: vi.fn(), closePanel: vi.fn(),
  cart: null, refreshCart: vi.fn(async () => undefined), setCart: vi.fn(), bindDemoCustomer: vi.fn(), switchIdentity: vi.fn(),
}
const response = (answer: string, conversationId = 'c1', toolCalls: unknown[] = []) => ({ answer, conversationId, toolCalls, suggestions: [], analysisSources: [], degraded: false, degradedReason: null })
const tree = (value: ShopContextValue = base) => <ShopContext.Provider value={value}><ChatProvider><Probe /></ChatProvider></ShopContext.Provider>
beforeEach(() => { stream.mockReset(); history.mockReset(); vi.mocked(base.refreshCart).mockClear() })

it('合并流式和最终工具调用，续用会话并在每轮后刷新购物车', async () => {
  stream.mockImplementation(async function* ({ conversationId }: { conversationId: string | null }) {
    yield { type: 'tool_call', call: { callId: 'call-1', toolName: 'set_cart_item', status: 'STARTED', summary: '开始' } }
    yield { type: 'tool_result', call: { callId: 'call-1', toolName: 'set_cart_item', status: 'SUCCEEDED', summary: '完成' } }
    yield { type: 'turn_complete', response: response(conversationId ? '第二轮' : '第一轮', 'c1', [{ callId: 'call-1', toolName: 'set_cart_item', status: 'SUCCEEDED', summary: '完成' }]) }
  })
  render(tree())
  await userEvent.click(screen.getByText('send'))
  await waitFor(() => expect(screen.getByTestId('messages')).toHaveTextContent('第一轮'))
  expect(screen.getByTestId('calls')).toHaveTextContent('call-1')
  expect(screen.getByTestId('calls')).not.toHaveTextContent('call-1|call-1')
  await userEvent.click(screen.getByText('next'))
  await waitFor(() => expect(screen.getByTestId('messages')).toHaveTextContent('第二轮'))
  expect(stream.mock.calls[0]?.[0].conversationId).toBeNull()
  expect(stream.mock.calls[1]?.[0].conversationId).toBe('c1')
  expect(stream.mock.calls[0]?.[0].clientRequestId).not.toBe(stream.mock.calls[1]?.[0].clientRequestId)
  expect(base.refreshCart).toHaveBeenCalledTimes(2)
  expect(screen.getByTestId('turns')).toHaveTextContent('2')
})

it('请求失败时移除空回答并显示错误', async () => {
  stream.mockImplementation(async function* () { throw new Error('offline') })
  render(tree())
  await userEvent.click(screen.getByText('send'))
  await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('服务暂时不可用'))
  expect(screen.getByTestId('messages')).toHaveTextContent('hello')
  expect(screen.getByTestId('messages')).not.toHaveTextContent('hello|')
})

it('打开历史对话后可续聊，重新开始不沿用旧会话', async () => {
  history.mockResolvedValue({ truncated: false, messages: [{ id: 'u1', role: 'user', content: '旧问题', turn: null }, { id: 'a1', role: 'assistant', content: '旧回答', turn: response('旧回答') }] })
  stream.mockImplementation(async function* () { yield { type: 'turn_complete', response: response('新回答') } })
  render(tree())
  await userEvent.click(screen.getByText('open'))
  await waitFor(() => expect(screen.getByTestId('messages')).toHaveTextContent('旧问题|旧回答'))
  await userEvent.click(screen.getByText('send'))
  await waitFor(() => expect(screen.getByTestId('messages')).toHaveTextContent('新回答'))
  expect(stream.mock.calls[0]?.[0].conversationId).toBe('c1')
  await userEvent.click(screen.getByText('new'))
  expect(screen.getByTestId('messages')).toHaveTextContent('')
  await userEvent.click(screen.getByText('next'))
  await waitFor(() => expect(stream).toHaveBeenCalledTimes(2))
  expect(stream.mock.calls[1]?.[0].conversationId).toBeNull()
})

it('主体切换清空消息，旧流的完成事件不会写入新主体', async () => {
  let finish!: () => void
  stream.mockImplementation(async function* () {
    await new Promise<void>(resolve => { finish = resolve })
    yield { type: 'turn_complete', response: { answer: 'private old answer', conversationId: 'old', toolCalls: [], suggestions: [], analysisSources: [] } }
  })
  const identityTree = (bound: boolean) => tree({ ...base, session: { ...base.session!, isBound: bound } })
  const result = render(identityTree(false))
  await userEvent.click(screen.getByText('send'))
  expect(screen.getByText('hello|')).toBeInTheDocument()
  result.rerender(identityTree(true))
  await act(async () => { finish() })
  await waitFor(() => expect(screen.queryByText(/private old answer/)).toBeNull())
  expect(screen.queryByText('old')).toBeNull()
  expect(screen.queryByText('hello|')).toBeNull()
})

it('视图切到订单再切回，消息与会话仍在（聊天状态在外壳层，不随视图销毁）', async () => {
  stream.mockImplementation(async function* () {
    yield { type: 'turn_complete', response: response('第一轮') }
  })
  const result = render(tree())
  await userEvent.click(screen.getByText('send'))
  await waitFor(() => expect(screen.getByTestId('messages')).toHaveTextContent('hello|第一轮'))
  result.rerender(tree({ ...base, view: 'orders', panel: 'cart' }))
  result.rerender(tree({ ...base, view: 'assistant' }))
  expect(screen.getByTestId('messages')).toHaveTextContent('hello|第一轮')
  expect(screen.getByTestId('conversation')).toHaveTextContent('c1')
})
