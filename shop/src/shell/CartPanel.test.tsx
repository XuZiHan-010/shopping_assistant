import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { CartPanel } from './CartPanel'

const mocks = vi.hoisted(() => ({
  submit: vi.fn(), push: vi.fn(), closePanel: vi.fn(), refreshCart: vi.fn(), listCoupons: vi.fn(),
}))
vi.mock('@/checkout/checkout', () => ({ createCheckout: () => ({ submit: mocks.submit }) }))
vi.mock('@/api/catalogApi', () => ({ listCoupons: mocks.listCoupons }))
vi.mock('@/api/shopApi', () => ({ setCartItem: vi.fn(), removeCartItem: vi.fn() }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('@/session/ShopContext', () => ({
  useShop: () => ({
    shopSlug: 'borough-100',
    session: { sessionId: 's1', shopSlug: 'borough-100', isBound: true, expiresAt: '2099-01-01' },
    cart: {
      items: [{ productId: 'p1', name: '切尔西靴', imageUrl: null, quantity: 1, unitPriceCents: 69900, lineTotalCents: 69900, stockBand: 'IN_STOCK' }],
      subtotalCents: 69900,
    },
    setCart: vi.fn(), refreshCart: mocks.refreshCart, bindDemoCustomer: vi.fn(), closePanel: mocks.closePanel,
  }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  mocks.refreshCart.mockResolvedValue(undefined)
  mocks.listCoupons.mockResolvedValue([])
})

it('提交订单成功后关闭购物车抽屉，并进入订单视图里这一单', async () => {
  mocks.submit.mockResolvedValue({ kind: 'placed', order: { id: 'o-9' } })
  render(<CartPanel />)
  await userEvent.click(screen.getByRole('button', { name: '提交订单' }))
  await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/borough-100/orders/o-9'))
  expect(mocks.closePanel).toHaveBeenCalledOnce()
  expect(mocks.listCoupons).toHaveBeenCalledWith('borough-100', 'zh-CN')
})

it('下单被拒时逐项列出不可用商品，不跳转、不关闭购物车', async () => {
  mocks.submit.mockResolvedValue({ kind: 'unavailable', items: [{ productId: 'p1', reason: 'OUT_OF_STOCK', stockBand: 'OUT_OF_STOCK' }] })
  render(<CartPanel />)
  await userEvent.click(screen.getByRole('button', { name: '提交订单' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('切尔西靴')
  expect(mocks.push).not.toHaveBeenCalled()
  expect(mocks.closePanel).not.toHaveBeenCalled()
})
