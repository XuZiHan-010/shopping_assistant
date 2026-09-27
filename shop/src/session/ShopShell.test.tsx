import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetSessionForTest } from '@/api/credentials'
import { apiErrorBody, json, stubBackend } from '@/test/fakeBackend'
import { ShopShell } from './ShopShell'

vi.mock('next/navigation', () => ({ usePathname: () => '/borough-100' }))

const guest = () =>
  json(201, { session_id: 'sess-1', role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' })
const emptyCart = () => json(200, { items: [], subtotal_cents: 0 })

beforeEach(() => resetSessionForTest())
afterEach(() => vi.unstubAllGlobals())

describe('店铺外壳', () => {
  it('进入店铺时创建访客会话，顶栏显示访客身份', async () => {
    stubBackend({ 'POST /api/v2/shop/sessions': guest, 'GET /api/v2/shop/cart': emptyCart })
    render(
      <ShopShell shopSlug="borough-100">
        <p>店铺内容</p>
      </ShopShell>,
    )
    expect(await screen.findByTestId('identity')).toHaveTextContent('访客')
    expect(screen.getByText('店铺内容')).toBeInTheDocument()
  })

  it('未知或未开放的店铺（403）统一显示不可用，不渲染店铺内容', async () => {
    stubBackend({ 'POST /api/v2/shop/sessions': () => json(403, apiErrorBody('RESOURCE_FORBIDDEN')) })
    render(
      <ShopShell shopSlug="nope">
        <p>店铺内容</p>
      </ShopShell>,
    )
    expect(await screen.findByText('该店铺不存在或暂未开放。')).toBeInTheDocument()
    expect(screen.queryByText('店铺内容')).toBeNull()
  })

  it('演示身份不可用（非演示部署）时给出提示，而不是静默失败', async () => {
    stubBackend({
      'POST /api/v2/shop/sessions': guest,
      'GET /api/v2/shop/cart': emptyCart,
      'POST /api/v2/shop/sessions/demo-customer': () => json(404, apiErrorBody('NOT_FOUND')),
    })
    render(
      <ShopShell shopSlug="borough-100">
        <p>店铺内容</p>
      </ShopShell>,
    )
    await userEvent.setup().click(await screen.findByRole('button', { name: '绑定演示顾客' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/演示身份暂不可用/))
    expect(screen.getByTestId('identity')).toHaveTextContent('访客')
  })

  it('绑定时购物车被调整（cart_adjusted）要提示', async () => {
    stubBackend({
      'POST /api/v2/shop/sessions': guest,
      'GET /api/v2/shop/cart': emptyCart,
      'POST /api/v2/shop/sessions/demo-customer': () =>
        json(200, { role: 'CUSTOMER', is_bound: true, expires_at: '2099-01-01T00:00:00Z', cart_adjusted: true }),
    })
    render(
      <ShopShell shopSlug="borough-100">
        <p>店铺内容</p>
      </ShopShell>,
    )
    await userEvent.setup().click(await screen.findByRole('button', { name: '绑定演示顾客' }))
    expect(await screen.findByText('部分商品因售罄或数量上限已调整。')).toBeInTheDocument()
    expect(screen.getByTestId('identity')).toHaveTextContent('演示顾客')
  })
})
