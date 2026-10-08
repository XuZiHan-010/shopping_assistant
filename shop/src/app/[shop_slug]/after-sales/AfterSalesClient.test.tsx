import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/errors'
import { AfterSalesClient } from './AfterSalesClient'

const preview = vi.fn()
const confirm = vi.fn()
const getCase = vi.fn()
vi.mock('@/api/afterSalesApi', () => ({
  previewAfterSale: (...args: unknown[]) => preview(...args),
  confirmAfterSale: (...args: unknown[]) => confirm(...args),
  listAfterSales: async () => [],
  getAfterSale: (...args: unknown[]) => getCase(...args),
  supplementAfterSale: async () => null,
}))
vi.mock('@/api/shopApi', () => ({
  getOrder: async () => ({
    id: 'order-1', items: [{ orderItemId: 'line-1', name: '围巾', quantity: 1,
      lineTotalCents: 1234 }],
  }),
}))

beforeEach(() => {
  preview.mockReset()
  confirm.mockReset()
  getCase.mockReset()
  getCase.mockResolvedValue(null)
  preview.mockResolvedValue({
    token: 'evidence', expiresAt: '2099-01-01T00:00:00Z',
    lines: [{ orderItemId: 'line-1', name: '围巾', quantity: 1, lineTotalCents: 1234 }],
    estimatedRefundCents: 1234, reason: '质量问题', summaryStatus: 'NOT_SHARED',
    conversationSummary: null,
  })
  confirm.mockResolvedValue({ id: 'sale-1', state: 'PENDING_MERCHANT' })
})

it('从订单视图进入指定售后单时直接打开该详情', async () => {
  getCase.mockResolvedValueOnce({
    id: 'case-1', orderId: 'order-1', type: 'REFUND_ONLY', state: 'PENDING_MERCHANT',
    reason: '质量问题', refundAmountCents: 1234, createdAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-01T00:00:00Z',
    lines: [], events: [], supplements: [], replies: [], conversationSummaryShared: false,
  })
  render(<AfterSalesClient caseId="case-1" />)
  expect(await screen.findByText('质量问题', { exact: false })).toBeInTheDocument()
  expect(getCase).toHaveBeenCalledWith('case-1')
})

it('shows server refund preview and requires explicit checkbox before confirmation', async () => {
  const user = userEvent.setup()
  render(<AfterSalesClient orderId="order-1" />)
  await screen.findByText('围巾')
  await user.type(screen.getByRole('textbox', { name: '申请原因' }), '质量问题')
  await user.click(screen.getByRole('button', { name: '预览申请' }))
  expect(await screen.findByText(/后端计算的预计可退金额：¥12\.34/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '确认提交' })).toBeDisabled()
  await user.click(screen.getByRole('checkbox', { name: '我已核对申请信息' }))
  await user.click(screen.getByRole('button', { name: '确认提交' }))
  expect(confirm).toHaveBeenCalledOnce()
  expect(confirm.mock.calls[0]?.[0].clientRequestId).toBe(preview.mock.calls[0]?.[0].clientRequestId)
})

it('renders the after-sales flow in English when requested', async () => {
  render(<AfterSalesClient orderId="order-1" locale="en-US" />)
  expect(screen.getByRole('heading', { name: 'After-sales service' })).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: 'Preview request' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'My after-sales cases' })).toBeInTheDocument()
})

it('shows the platform rule when the server rejects an expired request', async () => {
  preview.mockRejectedValueOnce(new ApiError(422, {
    code: 'GUARDRAIL_REJECTED',
    details: [{ reason: 'WINDOW_EXPIRED', rule_reference: '平台演示售后规则：签收后七天内申请' }],
  }))
  const user = userEvent.setup()
  render(<AfterSalesClient orderId="order-1" />)
  await screen.findByText('围巾')
  await user.click(screen.getByRole('button', { name: '预览申请' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('签收后七天内申请')
})

it('explains an expired request in English', async () => {
  preview.mockRejectedValueOnce(new ApiError(422, {
    code: 'GUARDRAIL_REJECTED',
    details: [{ reason: 'WINDOW_EXPIRED', rule_reference: '平台演示售后规则：签收后七天内申请' }],
  }))
  const user = userEvent.setup()
  render(<AfterSalesClient orderId="order-1" locale="en-US" />)
  await screen.findByText('围巾')
  await user.click(screen.getByRole('button', { name: 'Preview request' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('within 7 days after delivery')
})
