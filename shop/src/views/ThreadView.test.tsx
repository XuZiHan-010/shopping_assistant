import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ThreadView } from './ThreadView'

const chat = vi.hoisted(() => ({ useChat: vi.fn() }))
vi.mock('@/chat/ChatProvider', () => chat)

const turn = (answer: string) => ({
  id: answer, conversationId: 'c1', answer, toolCalls: [{ toolName: 'get_my_order', callId: 'call1', status: 'SUCCEEDED', summary: '已查到物流' }],
  analysisSources: [{ source: 'DATABASE', degraded: true, degradedReason: '订单库延迟' }], qualityStatus: 'DEGRADED', qualityNotes: [],
  degraded: true, degradedReason: '部分数据不可用', answerMode: 'SHOP_GUIDE', suggestions: ['还要多久？'], createdAt: '2026-09-01T00:00:00Z',
})
const state = () => ({ messages: [
  { id: 'u1', role: 'user', text: '订单到哪了？', toolCalls: [] },
  { id: 'a1', role: 'assistant', text: '已发货', toolCalls: turn('已发货').toolCalls, turn: turn('已发货') },
  { id: 'u2', role: 'user', text: '还有呢？', toolCalls: [] },
  { id: 'a2', role: 'assistant', text: '派送中', toolCalls: turn('派送中').toolCalls, turn: turn('派送中') },
], busy: false, error: null, historyTruncated: false, resetToNew: vi.fn(), send: vi.fn() })

beforeEach(() => { chat.useChat.mockReset(); chat.useChat.mockReturnValue(state()) })

it('renders messages, redacted tool steps and visible degradation', async () => {
  render(<ThreadView onOpenHistory={vi.fn()} />)
  const thread = screen.getByRole('region', { name: '和智能助手的对话' })
  expect(within(thread).getAllByText('Borough 智能助手')).toHaveLength(2)
  expect(within(thread).getByText('订单到哪了？').closest('li')?.className).toContain('userRow')
  expect(within(thread).getAllByText('本次回答已降级：部分数据不可用')).toHaveLength(2)
  expect(within(thread).getAllByText(/来源降级：订单库延迟/)).toHaveLength(2)
  expect(within(thread).getAllByRole('button', { name: '还要多久？' })).toHaveLength(1)
  await userEvent.setup().click(within(thread).getAllByRole('button', { name: '查了 1 步' })[0]!)
  expect(within(thread).getByText('查询订单')).toBeInTheDocument()
  expect(within(thread).getByText('已查到物流')).toBeInTheDocument()
  expect(thread).not.toHaveTextContent('call1')
})

it('opens history, starts a new conversation and sends last-answer suggestion', async () => {
  const onOpenHistory = vi.fn()
  const value = state()
  chat.useChat.mockReturnValue(value)
  render(<ThreadView onOpenHistory={onOpenHistory} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '对话记录' }))
  await user.click(screen.getByRole('button', { name: '还要多久？' }))
  await user.click(screen.getByRole('button', { name: '新对话' }))
  expect(onOpenHistory).toHaveBeenCalledOnce()
  expect(value.send).toHaveBeenCalledWith('还要多久？')
  expect(value.resetToNew).toHaveBeenCalledOnce()
})
