import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ProductDetail } from '@/types/shop'
import { ProductDetailBody } from './ProductDetailBody'
import { ProductSheet } from './ProductSheet'

const api = vi.hoisted(() => ({ getProduct: vi.fn() }))
const chat = vi.hoisted(() => ({ send: vi.fn() }))
vi.mock('@/api/catalogApi', () => api)
vi.mock('@/chat/ChatProvider', () => ({ useChat: () => chat }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/session/ShopContext', () => ({ useShop: () => ({ session: { sessionId: 's1' }, cart: null, setCart: vi.fn() }) }))

const product: ProductDetail = {
  id: 'p1', name: '羊绒围巾', shortDescription: '柔软保暖', description: '详细描述', priceCents: 25900,
  stockBand: 'OUT_OF_STOCK', imageUrl: null, sourceLocale: 'zh-CN', contentVersion: 1, category: '女装',
  requestedLocale: 'zh-CN', nameTranslationStatus: 'SOURCE', shortDescriptionTranslationStatus: 'SOURCE', descriptionTranslationStatus: 'SOURCE',
  attributes: [{ name: '材质', value: '羊绒', source: 'MERCHANT', nameTranslationStatus: 'SOURCE', valueTranslationStatus: 'SOURCE' }],
  missingAttributes: ['产地'],
}
beforeEach(() => { vi.clearAllMocks(); api.getProduct.mockResolvedValue(product) })

it('打开时读取商品，展示属性与后端列出的缺口，售罄不能加购', async () => {
  const user = userEvent.setup()
  render(<ProductSheet shopSlug="borough-100" productId="p1" onClose={vi.fn()} />)
  expect(api.getProduct).toHaveBeenCalledWith('borough-100', 'p1', 'zh-CN')
  expect(await screen.findByRole('dialog', { name: '羊绒围巾' })).toBeInTheDocument()
  expect(screen.getByText('材质')).toBeInTheDocument()
  expect(screen.getByText('产地')).toBeInTheDocument()
  expect(screen.getByText(/店家暂未提供/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '加入购物车' })).toBeDisabled()
  expect(screen.queryByText('p1')).toBeNull() // 内部商品 ID 不当作商品编号展示
  expect(screen.getByText('女装')).toBeInTheDocument() // 类目取后端源值
  await user.click(screen.getByRole('button', { name: /问问智能助手.*产地/ }))
  expect(chat.send).toHaveBeenCalledWith(expect.stringContaining('羊绒围巾'))
  expect(chat.send).toHaveBeenCalledWith(expect.stringContaining('产地'))
})

it('Esc 关闭浮层并把焦点还给触发按钮', async () => {
  const user = userEvent.setup()
  function Host() {
    const [open, setOpen] = useState(false)
    return <><button onClick={() => setOpen(true)}>打开商品</button>{open && <ProductSheet shopSlug="borough-100" productId="p1" onClose={() => setOpen(false)} />}</>
  }
  render(<Host />)
  await user.click(screen.getByRole('button', { name: '打开商品' }))
  await screen.findByRole('dialog')
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
  await waitFor(() => expect(screen.getByRole('button', { name: '打开商品' })).toHaveFocus())
})

it('缺口为空时不显示缺口行', async () => {
  api.getProduct.mockResolvedValue({ ...product, missingAttributes: [] })
  render(<ProductSheet shopSlug="borough-100" productId="p1" onClose={vi.fn()} />)
  await screen.findByRole('dialog')
  expect(screen.queryByText(/店家暂未提供/)).toBeNull()
})

it('完整商品页与浮层复用同一详情结构，英文缺口名称按固定词表显示', () => {
  render(<ProductDetailBody product={{ ...product, requestedLocale: 'en-US' }} shopSlug="borough-100" />)
  expect(screen.getByRole('heading', { name: '羊绒围巾' })).toBeInTheDocument()
  expect(screen.getByText('Origin')).toBeInTheDocument()
  expect(screen.getByText(/Not provided by the merchant/)).toBeInTheDocument()
})

it('商品图片加载失败时显示暂无图片占位', () => {
  render(<ProductDetailBody product={{ ...product, imageUrl: '/demo/products/01.webp' }} shopSlug="borough-100" />)
  fireEvent.error(screen.getByRole('img', { name: '羊绒围巾' }))
  expect(screen.getByText('暂无图片')).toBeInTheDocument()
})
