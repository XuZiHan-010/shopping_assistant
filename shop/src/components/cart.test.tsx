import { readFileSync } from 'node:fs'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Cart } from '@/types/shop'
import type { ShopSession } from '@/types/session'
import { CartView } from './CartView'

const guest: ShopSession = {
  sessionId: 's',
  shopSlug: 'borough-100',
  isBound: false,
  expiresAt: '2099-01-01T00:00:00Z',
}
const bound: ShopSession = { ...guest, isBound: true }
const item = (productId: string, name: string, quantity = 1) => ({
  productId,
  name,
  imageUrl: null,
  quantity,
  unitPriceCents: 100,
  lineTotalCents: 777,
  stockBand: 'IN_STOCK' as const,
})
const cart = (items: Cart['items'], subtotalCents = 99999): Cart => ({ items, subtotalCents })

const base = {
  coupons: [],
  couponId: null,
  unavailable: [],
  error: null,
  submitting: false,
  onCouponChange: vi.fn(),
  onQuantityChange: vi.fn(),
  onRemove: vi.fn(),
  onSubmit: vi.fn(),
  onBind: vi.fn(),
}

describe('C3 购物车页', () => {
  it('未绑定访客的购物车页明示刷新后无法找回，且不说「已删除」', () => {
    render(<CartView {...base} session={guest} cart={cart([])} />)
    expect(screen.getByText(/未绑定身份时刷新后无法找回购物车/)).toBeInTheDocument()
    expect(screen.getByText(/绑定演示身份后可恢复/)).toBeInTheDocument()
    expect(screen.queryByText(/已删除|已清空/)).toBeNull()
  })

  it('已绑定顾客不显示刷新提示', () => {
    render(<CartView {...base} session={bound} cart={cart([])} />)
    expect(screen.queryByText(/未绑定身份时刷新后无法找回购物车/)).toBeNull()
  })

  it('小计与行金额直接展示后端值，不重算', () => {
    render(<CartView {...base} session={bound} cart={cart([item('p1', '围巾', 2)], 99999)} />)
    expect(screen.getByText('¥999.99')).toBeInTheDocument() // 后端小计，即使与行金额对不上
    expect(screen.getByText('¥7.77')).toBeInTheDocument()
  })

  it('不可用项逐项展示，且仍留在购物车里由顾客决定', () => {
    render(
      <CartView
        {...base}
        session={bound}
        cart={cart([item('p1', '围巾'), item('p2', '手套')])}
        unavailable={[{ productId: 'p2', reason: 'INSUFFICIENT_STOCK', stockBand: 'LOW_STOCK' }]}
      />,
    )
    const alert = screen.getByRole('alert')
    expect(within(alert).getByText(/手套/)).toBeInTheDocument()
    expect(within(alert).getByText(/库存不足/)).toBeInTheDocument()
    expect(screen.getAllByRole('listitem').some((li) => li.textContent?.includes('手套'))).toBe(true)
  })

  it('已下架商品与售罄各自说明原因', () => {
    render(
      <CartView
        {...base}
        session={bound}
        cart={cart([item('p1', '围巾'), item('p2', '手套')])}
        unavailable={[
          { productId: 'p1', reason: 'DELISTED', stockBand: 'OUT_OF_STOCK' },
          { productId: 'p2', reason: 'OUT_OF_STOCK', stockBand: 'OUT_OF_STOCK' },
        ]}
      />,
    )
    const alert = screen.getByRole('alert')
    expect(within(alert).getByText(/已下架/)).toBeInTheDocument()
    expect(within(alert).getByText(/已售罄/)).toBeInTheDocument()
  })

  it('结账明确标注演示，不产生真实扣款', () => {
    render(<CartView {...base} session={bound} cart={cart([item('p1', '围巾')])} />)
    expect(screen.getByText(/不产生真实扣款/)).toBeInTheDocument()
  })

  it('未绑定访客不能提交订单，并被引导绑定演示身份', () => {
    render(<CartView {...base} session={guest} cart={cart([item('p1', '围巾')])} />)
    expect(screen.getByRole('button', { name: '提交订单' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /绑定演示顾客/ })).toBeEnabled()
  })

  it('前端不计算订单合计（源码不含 reduce 求和与金额乘法）', () => {
    for (const file of ['src/components/CartView.tsx', 'src/shell/CartPanel.tsx']) {
      const source = readFileSync(file, 'utf-8')
      expect(source).not.toMatch(/\.reduce\(/)
      expect(source).not.toMatch(/(?:priceCents|PriceCents)\s*\*/)
    }
  })
})
