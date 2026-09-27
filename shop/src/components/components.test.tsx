import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Product } from '@/types/shop'
import { AttributeTable } from './AttributeTable'
import { ProductCard } from './ProductCard'
import { StockBadge } from './StockBadge'
import { AddToCartButton } from './AddToCartButton'
import { CouponList } from './CouponList'

vi.mock('@/session/ShopContext', () => ({
  useShop: () => ({ cart: null, setCart: vi.fn(), session: { sessionId: 'test' } }),
}))

const product = (stockBand: Product['stockBand']): Product => ({
  id: 'p1',
  name: '羊绒围巾',
  shortDescription: '柔软保暖',
  priceCents: 25900,
  stockBand,
  imageUrl: null,
  sourceLocale: 'zh-CN', contentVersion: 1, requestedLocale: 'zh-CN',
  nameTranslationStatus: 'SOURCE', shortDescriptionTranslationStatus: 'SOURCE',
})

describe('C1 商品展示', () => {
  it('商品卡片只渲染库存三档，不渲染任何库存数量', () => {
    render(<ProductCard shopSlug="borough-100" product={product('LOW_STOCK')} />)
    expect(screen.queryByText(/\d+\s*件/)).toBeNull()
    expect(screen.getByText('紧张')).toBeInTheDocument()
  })

  it.each([
    ['IN_STOCK', '有货'],
    ['LOW_STOCK', '紧张'],
    ['OUT_OF_STOCK', '售罄'],
  ] as const)('库存档 %s 显示为「%s」', (band, label) => {
    render(<ProductCard shopSlug="borough-100" product={product(band)} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('价格直接展示后端给的分，格式化为元', () => {
    render(<ProductCard shopSlug="borough-100" product={product('IN_STOCK')} />)
    expect(screen.getByText('¥259.00')).toBeInTheDocument()
  })

  it('缺失属性显示「商家未提供」而不是空行，且该行仍在', () => {
    render(<AttributeTable attributes={[{ name: '产地', value: null, source: 'MERCHANT', nameTranslationStatus: 'SOURCE', valueTranslationStatus: 'SOURCE' }]} />)
    expect(screen.getByText('产地')).toBeInTheDocument()
    expect(screen.getByText('商家未提供')).toBeInTheDocument()
  })

  it('空白字符串同样视为缺失', () => {
    render(<AttributeTable attributes={[{ name: '材质', value: '  ', source: 'MERCHANT', nameTranslationStatus: 'SOURCE', valueTranslationStatus: 'SOURCE' }]} />)
    expect(screen.getByText('商家未提供')).toBeInTheDocument()
  })

  it('演示数据来源的属性带标注，不冒充商家原文', () => {
    render(<AttributeTable attributes={[{ name: '克重', value: '200g', source: 'DEMO', nameTranslationStatus: 'SOURCE', valueTranslationStatus: 'SOURCE' }]} />)
    expect(screen.getByText('200g')).toBeInTheDocument()
    expect(screen.getByText('演示数据')).toBeInTheDocument()
  })

  it('机器译文和缺译回退在顾客商品卡片上明确标记', () => {
    render(<ProductCard shopSlug="borough-100" product={{ ...product('IN_STOCK'), requestedLocale: 'en-US', nameTranslationStatus: 'MACHINE', shortDescriptionTranslationStatus: 'FALLBACK' }} />)
    expect(screen.getByText('Machine translation')).toBeInTheDocument()
    expect(screen.getByText('Original text · translation unavailable')).toBeInTheDocument()
  })

  it('属性名和值分别标记机器译文与源文回退', () => {
    render(<AttributeTable locale="en-US" attributes={[{ name: 'Material', value: '羊绒', source: 'MERCHANT', nameTranslationStatus: 'MACHINE', valueTranslationStatus: 'FALLBACK' }]} />)
    expect(screen.getByText('Machine translation')).toBeInTheDocument()
    expect(screen.getByText('Original text · translation unavailable')).toBeInTheDocument()
  })

  it('英文商品页的库存与加购按钮使用英文文案', () => {
    render(<><StockBadge band="LOW_STOCK" locale="en-US" /><AddToCartButton productId="p1" soldOut={false} locale="en-US" /></>)
    expect(screen.getByText('Low stock')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to cart' })).toBeInTheDocument()
  })

  it('英文店铺页的优惠券金额口径与来源提示使用英文', () => {
    render(<CouponList locale="en-US" coupons={[{
      id: 'c1', name: '满减券', kind: 'AMOUNT_OFF', minSpendCents: 10000,
      amountOffCents: 1000, discountBps: null, productIds: [],
      startsAt: '2026-01-01T00:00:00Z', endsAt: '2027-01-01T00:00:00Z',
    }]} />)
    expect(screen.getByRole('heading', { name: 'Available coupons' })).toBeInTheDocument()
    expect(screen.getByText('Spend ¥100.00, save ¥10.00')).toBeInTheDocument()
    expect(screen.getByText('Original coupon name')).toBeInTheDocument()
  })
})
