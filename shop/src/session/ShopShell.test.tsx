import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { resetSessionForTest } from '@/api/credentials'
import { apiErrorBody, json, stubBackend } from '@/test/fakeBackend'
import { ShopShell } from './ShopShell'
import { LocaleProvider } from '@/i18n/LocaleProvider'

vi.mock('next/navigation', () => ({ usePathname: () => '/borough-100', useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }))

const guest = () =>
  json(201, { session_id: 'sess-1', role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' })
const emptyCart = () => json(200, { items: [], subtotal_cents: 0 })

beforeEach(() => resetSessionForTest())
afterEach(() => vi.unstubAllGlobals())

describe('店铺外壳', () => {
  it('英文模式的导航和演示身份入口使用英文', async () => {
    stubBackend({ 'POST /api/v2/shop/sessions': guest, 'GET /api/v2/shop/cart': emptyCart })
    render(<LocaleProvider initialLocale="en-US"><ShopShell shopSlug="borough-100"><p>Store</p></ShopShell></LocaleProvider>)
    expect(await screen.findByTestId('identity')).toHaveTextContent('Guest')
    const nav = screen.getByRole('navigation', { name: 'Store views' })
    expect(within(nav).getByRole('link', { name: 'Assistant' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Orders' })).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Guest' }))
    expect(within(screen.getByRole('group', { name: 'Guest' })).getByRole('button', { name: 'Use demo shopper' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '绑定演示顾客' })).not.toBeInTheDocument()
  })
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
    await screen.findByRole('button', { name: '绑定演示顾客' })
    await userEvent.setup().click(await screen.findByRole('button', { name: '访客' }))
    await userEvent.setup().click(within(await screen.findByRole('group', { name: '访客' })).getByRole('button', { name: '绑定演示顾客' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/演示身份暂不可用/))
    expect(screen.getByTestId('identity')).toHaveTextContent('访客')
  })

  it('顶栏两个视图入口标出当前视图；访客不请求订单，身份菜单说明演示身份', async () => {
    const backend = stubBackend({ 'POST /api/v2/shop/sessions': guest, 'GET /api/v2/shop/cart': emptyCart })
    render(<ShopShell shopSlug="borough-100"><p>店铺内容</p></ShopShell>)
    await screen.findByRole('button', { name: '绑定演示顾客' })
    const nav = screen.getByRole('navigation', { name: '店铺视图' })
    expect(within(nav).getByRole('link', { name: '智能助手' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: '订单' })).not.toHaveAttribute('aria-current')
    await userEvent.setup().click(screen.getByRole('button', { name: '访客' }))
    const menu = await screen.findByRole('group', { name: '访客' })
    expect(within(menu).getByText('演示身份，非真实登录。')).toBeInTheDocument()
    expect(within(menu).getByRole('button', { name: '绑定演示顾客' })).toBeInTheDocument()
    expect(backend.called('GET /api/v2/shop/orders')).toHaveLength(0)
  })

  it('绑定后「订单」角标只统计待付款订单，身份菜单改为退出', async () => {
    const summary = (id: string, payment: 'PENDING' | 'PAID') => ({
      id, payment_status: payment, fulfillment_status: 'NOT_SHIPPED', after_sale_status: 'NONE',
      total_cents: 100, item_count: 1, created_at: '2026-09-30T00:00:00Z', pay_by: '2026-09-30T00:30:00Z',
      lead_item: { product_id: 'p1', name: '商品', image_url: null }, last_event_at: '2026-09-30T00:00:00Z',
    })
    const backend = stubBackend({
      'POST /api/v2/shop/sessions': guest,
      'GET /api/v2/shop/cart': emptyCart,
      'POST /api/v2/shop/sessions/demo-customer': () =>
        json(200, { role: 'CUSTOMER', is_bound: true, expires_at: '2099-01-01T00:00:00Z', cart_adjusted: false }),
      'GET /api/v2/shop/orders': () =>
        json(200, { items: [summary('o1', 'PENDING'), summary('o2', 'PAID')], has_more: false, next_cursor: null }),
    })
    render(<ShopShell shopSlug="borough-100"><p>店铺内容</p></ShopShell>)
    await screen.findByRole('button', { name: '绑定演示顾客' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '访客' }))
    await user.click(within(await screen.findByRole('group', { name: '访客' })).getByRole('button', { name: '绑定演示顾客' }))
    const orders = within(screen.getByRole('navigation', { name: '店铺视图' })).getByRole('link', { name: '订单' })
    expect(await within(orders).findByText('1')).toBeInTheDocument()
    expect(backend.called('GET /api/v2/shop/orders').length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: '演示顾客' }))
    const menu = await screen.findByRole('group', { name: '演示顾客' })
    expect(within(menu).getByRole('button', { name: '退出演示身份' })).toBeInTheDocument()
    expect(within(menu).getByText('演示身份，非真实登录。')).toBeInTheDocument()
  })

  it('?panel=memory 进入时直接打开「我记住的」页签，并从地址栏去掉该参数', async () => {
    window.history.replaceState(null, '', '/borough-100?panel=memory')
    const backend = stubBackend({ 'POST /api/v2/shop/sessions': guest, 'GET /api/v2/shop/cart': emptyCart })
    render(<ShopShell shopSlug="borough-100"><p>店铺内容</p></ShopShell>)
    const drawer = await screen.findByRole('dialog', { name: '动态' })
    expect(within(drawer).getByRole('tab', { name: '我记住的' })).toHaveAttribute('aria-selected', 'true')
    expect(within(drawer).getByText('记忆只对绑定的演示顾客开放。')).toBeInTheDocument()
    expect(window.location.search).toBe('')
    expect(backend.called('GET /api/v2/shop/memories')).toHaveLength(0)
    window.history.replaceState(null, '', '/')
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
    await screen.findByRole('button', { name: '绑定演示顾客' })
    await userEvent.setup().click(await screen.findByRole('button', { name: '访客' }))
    await userEvent.setup().click(within(await screen.findByRole('group', { name: '访客' })).getByRole('button', { name: '绑定演示顾客' }))
    expect(await screen.findByText('部分商品因售罄或数量上限已调整。')).toBeInTheDocument()
    expect(screen.getByTestId('identity')).toHaveTextContent('演示顾客')
  })
})
