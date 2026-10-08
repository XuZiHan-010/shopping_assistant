import { createRef } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ActivityDrawer } from './ActivityDrawer'

const mocks = vi.hoisted(() => ({
  useChat: vi.fn(), useShop: vi.fn(), list: vi.fn(), remove: vi.fn(), memoryList: vi.fn(), memoryRemove: vi.fn(), preference: vi.fn(),
}))
vi.mock('@/chat/ChatProvider', () => ({ useChat: mocks.useChat }))
vi.mock('@/session/ShopContext', () => ({ useShop: mocks.useShop }))
vi.mock('@/api/conversationsApi', () => ({ listConversations: mocks.list, deleteConversation: mocks.remove }))
vi.mock('@/api/memoryApi', () => ({ listCustomerMemories: mocks.memoryList, deleteCustomerMemory: mocks.memoryRemove, setCustomerMemoryPreference: mocks.preference }))

const record = (question: string) => ({ question, elapsedMs: 1250, turn: { degraded: false, degradedReason: null, toolCalls: [{ callId: question, toolName: 'get_my_order', status: 'SUCCEEDED', summary: '已查到物流' }], analysisSources: [{ source: 'DATABASE', degraded: false, degradedReason: null }] } })
const chatState = () => ({ turns: [record('第一问'), record('第二问')], messages: [{ role: 'user', text: '当前问题' }], conversationId: 'c1', directoryVersion: 0, busy: false, resetToNew: vi.fn(), openConversation: vi.fn(async () => undefined), onDeleted: vi.fn(), setError: vi.fn() })

beforeEach(() => {
  for (const value of Object.values(mocks)) value.mockReset()
  mocks.useChat.mockReturnValue(chatState())
  mocks.useShop.mockReturnValue({ session: { isBound: true, sessionId: 's1' }, bindDemoCustomer: vi.fn() })
  mocks.list.mockResolvedValue({ items: [], nextCursor: null })
  mocks.remove.mockResolvedValue(undefined)
  mocks.memoryList.mockResolvedValue({ memoryEnabled: true, nextCursor: null, items: [{ id: 'm1', category: 'style', key: 'color', value: '喜欢素色', expiresAt: '2027-01-01T00:00:00Z' }] })
  mocks.memoryRemove.mockResolvedValue(undefined)
  mocks.preference.mockResolvedValue(1)
})

it('shows the two turns with visible process details and keyboard focus restoration', async () => {
  const onClose = vi.fn()
  const triggerRef = createRef<HTMLButtonElement>()
  const view = render(<><button ref={triggerRef}>动态入口</button><ActivityDrawer open onClose={onClose} triggerRef={triggerRef} /></>)
  expect(screen.getByRole('dialog', { name: '动态' })).toBeInTheDocument()
  expect(within(screen.getByRole('dialog', { name: '动态' })).getByRole('button', { name: '关闭' })).toHaveFocus()
  expect(screen.getByText('第二问')).toBeInTheDocument()
  expect(screen.getByText('get_my_order')).toBeInTheDocument()
  expect(screen.getByText('用时 1.3 秒')).toBeInTheDocument()
  await userEvent.setup().click(screen.getByRole('button', { name: '‹' }))
  expect(screen.getByText('第一问')).toBeInTheDocument()
  await userEvent.setup().keyboard('{Escape}')
  expect(onClose).toHaveBeenCalledOnce()
  view.rerender(<><button ref={triggerRef}>动态入口</button><ActivityDrawer open={false} onClose={onClose} triggerRef={triggerRef} /></>)
  expect(triggerRef.current).toHaveFocus()
})

it('opens memory tab, confirms purge with count, and never fetches as guest', async () => {
  const user = userEvent.setup()
  const view = render(<ActivityDrawer open onClose={vi.fn()} initialTab="memory" />)
  expect(await screen.findByText('喜欢素色')).toBeInTheDocument()
  await user.click(screen.getByRole('switch', { name: '允许智能助手记住我的偏好' }))
  expect(screen.getByText(/关闭记忆会清空已保存的 1 条偏好/)).toBeInTheDocument()
  expect(mocks.preference).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '取消' }))
  expect(mocks.preference).not.toHaveBeenCalled()
  await user.click(screen.getByRole('switch', { name: '允许智能助手记住我的偏好' }))
  await user.click(screen.getByRole('button', { name: '确认' }))
  await waitFor(() => expect(mocks.preference).toHaveBeenCalledWith(false))
  expect(screen.queryByText('喜欢素色')).not.toBeInTheDocument()
  mocks.useShop.mockReturnValue({ session: { isBound: false, sessionId: 's2' }, bindDemoCustomer: vi.fn() })
  mocks.memoryList.mockClear()
  view.rerender(<ActivityDrawer open onClose={vi.fn()} initialTab="memory" />)
  expect(screen.getByText('记忆只对绑定的演示顾客开放。')).toBeInTheDocument()
  expect(mocks.memoryList).not.toHaveBeenCalled()
})

it('deletes one memory without clearing the preference and closes via backdrop', async () => {
  const onClose = vi.fn()
  const user = userEvent.setup()
  render(<ActivityDrawer open onClose={onClose} initialTab="memory" />)
  await screen.findByText('喜欢素色')
  await user.click(screen.getByRole('button', { name: '删除：color' }))
  await waitFor(() => expect(mocks.memoryRemove).toHaveBeenCalledWith('m1'))
  expect(screen.queryByText('喜欢素色')).not.toBeInTheDocument()
  expect(mocks.preference).not.toHaveBeenCalled()
  await user.click(document.querySelector('button[aria-hidden="true"]') as HTMLButtonElement)
  expect(onClose).toHaveBeenCalledOnce()
})

it('shows an empty process state when no turn has finished', () => {
  mocks.useChat.mockReturnValue({ ...chatState(), turns: [] })
  render(<ActivityDrawer open onClose={vi.fn()} />)
  expect(screen.getByText(/还没有对话。向智能助手提问后/)).toBeInTheDocument()
})

it('lists, opens and deletes conversations in the history tab', async () => {
  mocks.list.mockResolvedValue({ items: [{ id: 'c1', title: '围巾怎么选', updatedAt: '2026-09-01T00:00:00Z' }, { id: 'c2', title: '旧问题', updatedAt: '2026-09-01T00:00:00Z' }], nextCursor: null })
  const chat = chatState()
  mocks.useChat.mockReturnValue(chat)
  const user = userEvent.setup()
  render(<ActivityDrawer open onClose={vi.fn()} initialTab="history" />)
  await user.click(await screen.findByRole('button', { name: '围巾怎么选' }))
  expect(chat.openConversation).toHaveBeenCalledWith('c1')
  await user.click(screen.getByRole('button', { name: '删除：旧问题' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: '旧问题' })).not.toBeInTheDocument())
  expect(chat.onDeleted).toHaveBeenCalledWith('c2')
})

it('shows a newly created current conversation before the directory catches up', async () => {
  render(<ActivityDrawer open onClose={vi.fn()} initialTab="history" />)
  expect(await screen.findByText('当前问题')).toBeInTheDocument()
  expect(screen.getByText('当前').parentElement).toHaveAttribute('aria-current', 'true')
})

it('历史目录失败时可重试，下一页追加而不覆盖第一页', async () => {
  mocks.list.mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce({ items: [{ id: 'c1', title: '第一页', updatedAt: '2026-09-01T00:00:00Z' }], nextCursor: 'CUR-2' })
    .mockResolvedValueOnce({ items: [{ id: 'c2', title: '第二页', updatedAt: '2026-09-01T00:00:00Z' }], nextCursor: null })
  render(<ActivityDrawer open onClose={vi.fn()} initialTab="history" />)
  expect(await screen.findByRole('alert')).toHaveTextContent('无法加载对话记录')
  expect(screen.queryByText('还没有对话记录。')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await screen.findByRole('button', { name: '第一页' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '加载更多' }))
  expect(await screen.findByRole('button', { name: '第二页' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '第一页' })).toBeInTheDocument()
  expect(mocks.list).toHaveBeenLastCalledWith('CUR-2')
})

it('删除当前对话会回到新建态，删除失败保留目录项并提示', async () => {
  mocks.list.mockResolvedValue({ items: [{ id: 'c1', title: '当前', updatedAt: '2026-09-01T00:00:00Z' }], nextCursor: null })
  const chat = chatState()
  mocks.useChat.mockReturnValue(chat)
  render(<ActivityDrawer open onClose={vi.fn()} initialTab="history" />)
  await screen.findByRole('button', { name: '当前' })
  mocks.remove.mockRejectedValueOnce(new Error('offline'))
  await userEvent.click(screen.getByRole('button', { name: '删除：当前' }))
  await waitFor(() => expect(chat.setError).toHaveBeenCalledWith('删除失败，请重试。'))
  expect(screen.getByRole('button', { name: '当前' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '删除：当前' }))
  await waitFor(() => expect(chat.onDeleted).toHaveBeenCalledWith('c1'))
  expect(screen.queryByRole('button', { name: '当前' })).toBeNull()
})

it('没有记忆时显示空状态', async () => {
  mocks.memoryList.mockResolvedValue({ memoryEnabled: true, nextCursor: null, items: [] })
  render(<ActivityDrawer open onClose={vi.fn()} initialTab="memory" />)
  expect(await screen.findByText(/还没有记住任何偏好/)).toBeInTheDocument()
})
