import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderToString } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { OrderSummaryView, Product, StoreProfile } from '@/types/shop'
import { translate } from '@/i18n/LocaleProvider'
import { HomeView } from './HomeView'
import { ProductArt } from './ProductArt'
import { QUICK_PROMPTS } from './quickPrompts'

const mocks = vi.hoisted(() => ({
  send: vi.fn(), listOrders: vi.fn(), listProducts: vi.fn(), bind: vi.fn(), openPanel: vi.fn(), push: vi.fn(),
  session: { isBound: true, sessionId: 's1' } as { isBound: boolean; sessionId: string } | null,
  messages: [] as { id: string }[],
}))
vi.mock('@/chat/ChatProvider', () => ({ useChat: () => ({ send: mocks.send, messages: mocks.messages }) }))
vi.mock('@/session/ShopContext', () => ({ useShop: () => ({ shopSlug: 'borough-100', session: mocks.session, bindDemoCustomer: mocks.bind, openPanel: mocks.openPanel }) }))
vi.mock('@/api/shopApi', () => ({ listOrders: mocks.listOrders }))
vi.mock('@/api/catalogApi', () => ({ listProducts: mocks.listProducts }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }))

const product = (id: string, stockBand: Product['stockBand'] = 'IN_STOCK'): Product => ({
  id, name: `商品${id}`, shortDescription: '好物', priceCents: 23900, stockBand, imageUrl: null,
  sourceLocale: 'zh-CN', contentVersion: 1, requestedLocale: 'zh-CN', category: '鞋靴',
  nameTranslationStatus: 'SOURCE', shortDescriptionTranslationStatus: 'SOURCE',
})
const order = (id: string, fulfillmentStatus: OrderSummaryView['fulfillmentStatus'], paymentStatus: OrderSummaryView['paymentStatus'] = 'PAID'): OrderSummaryView => ({
  id, paymentStatus, fulfillmentStatus, afterSaleStatus: 'NONE', totalCents: 23900, itemCount: 1,
  createdAt: '2026-09-28T08:00:00Z', payBy: '2026-09-30T08:00:00Z',
  leadItem: { productId: 'p1', name: `商品${id}`, imageUrl: null }, lastEventAt: '2026-09-29T08:00:00Z',
})
const store: StoreProfile = { shopSlug: 'borough-100', displayName: 'Borough 商家100', rulesSummary: '七天内可退货' }
const popular = Array.from({ length: 8 }, (_, i) => product(`p${i + 1}`, i === 0 ? 'LOW_STOCK' : 'IN_STOCK'))
const base = { popular, store, coupons: [], locale: 'zh-CN' as const }

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  // 问候语按运行环境的本地时间取：用本地时间构造，测试才不依赖机器所在时区（CI 是 UTC）。
  vi.setSystemTime(new Date(2026, 8, 29, 20, 0, 0))
  mocks.session = { isBound: true, sessionId: 's1' }; mocks.messages = []
  mocks.listOrders.mockResolvedValue([
    order('delivery', 'OUT_FOR_DELIVERY'), order('pending', 'NOT_SHIPPED', 'PENDING'),
    order('transit', 'IN_TRANSIT'), order('done', 'DELIVERED'), order('shipped', 'SHIPPED'),
  ])
  mocks.listProducts.mockResolvedValue([...popular, product('extra')])
})
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

describe('智能助手首页', () => {
  it('按本地时间问候并展示真实订单概况；访客不读取订单', async () => {
    const view = render(<HomeView {...base} />)
    expect(screen.getByRole('heading', { name: '晚上好，欢迎回来' })).toBeInTheDocument()
    expect(await screen.findByText(/4 单进行中/)).toBeInTheDocument()
    expect(screen.getByText(/1 单今天派送中/)).toBeInTheDocument()
    expect(screen.getByText(/1 单待付款/)).toBeInTheDocument()
    expect(screen.queryByText(/顾客姓名/)).toBeNull()

    mocks.session = null
    view.rerender(<HomeView {...base} />)
    expect(screen.getByRole('heading', { name: '晚上好' })).toBeInTheDocument()
    expect(screen.getAllByText(/绑定演示顾客后/)).toHaveLength(2)
  })

  it('服务端渲染不输出依赖时区的问候与日期，避免与顾客本机时间水合不一致', () => {
    const html = renderToString(<HomeView {...base} />)
    expect(html).not.toMatch(/早上好|下午好|晚上好/)
    expect(html).not.toContain('星期')
    expect(html).toContain('通勤穿的鞋')
  })

  it('英文概况句使用英文标点并区分单复数', async () => {
    mocks.listOrders.mockResolvedValue([order('delivery', 'OUT_FOR_DELIVERY'), order('pending', 'NOT_SHIPPED', 'PENDING')])
    const view = render(<HomeView {...base} locale="en-US" />)
    const summary = await screen.findByText(/^\d+ orders? in progress/)
    expect(summary.textContent).toBe('2 orders in progress, 1 out for delivery today. 1 awaiting payment.')
    expect(summary.textContent).not.toContain('。')
    expect(screen.getByRole('heading', { name: 'Good evening, welcome back' })).toBeInTheDocument()

    mocks.listOrders.mockResolvedValue([order('transit', 'IN_TRANSIT')])
    view.unmount()
    render(<HomeView {...base} locale="en-US" />)
    expect((await screen.findByText(/^\d+ orders? in progress/)).textContent).toBe('1 order in progress.')
    expect(screen.getByText('1 order')).toBeInTheDocument()
  })

  it('访客绝不请求订单，快捷卡片发送普通文本', async () => {
    mocks.session = null
    render(<HomeView {...base} />)
    expect(mocks.listOrders).not.toHaveBeenCalled()
    const quick = screen.getByRole('group', { name: '快捷提问' })
    const cards = within(quick).getAllByRole('button')
    expect(cards).toHaveLength(QUICK_PROMPTS.length)
    for (const [index, prompt] of QUICK_PROMPTS.entries()) {
      const text = translate('zh-CN', prompt.key)
      await userEvent.click(cards[index]!)
      // 点击只发送这一条文案本身，不附带任何预置内容。
      expect(mocks.send.mock.calls[index]).toEqual([text])
    }
  })

  it('快捷提问覆盖五个顾客 Skill 与一条规则问答（D-N5-4），中英一一对应', () => {
    expect(QUICK_PROMPTS.length).toBeGreaterThanOrEqual(6)
    expect(new Set(QUICK_PROMPTS.map(prompt => prompt.capability))).toEqual(new Set([
      'search-discovery', 'purchase-research', 'planning-goals',
      'after-sales-service', 'memory-personalization', 'platform-rules',
    ]))
    expect(new Set(QUICK_PROMPTS.map(prompt => prompt.key)).size).toBe(QUICK_PROMPTS.length)
    for (const prompt of QUICK_PROMPTS) {
      const zh = translate('zh-CN', prompt.key)
      const en = translate('en-US', prompt.key)
      expect(zh).toMatch(/[一-鿿]/)
      expect(en, `${prompt.key} 缺英文`).not.toMatch(/[一-鿿]/)
      expect(en.trim().length).toBeGreaterThan(10)
    }
  })

  it('英文模式下快捷卡片显示并发送英文文案', async () => {
    mocks.session = null
    render(<HomeView {...base} locale="en-US" />)
    const cards = within(screen.getByRole('group', { name: 'Suggested questions' })).getAllByRole('button')
    await userEvent.click(cards[0]!)
    expect(mocks.send).toHaveBeenCalledWith(translate('en-US', QUICK_PROMPTS[0]!.key))
  })

  it('进行中最多三单，按派送、待付款、运输顺序；按钮分流正确', async () => {
    render(<HomeView {...base} />)
    const panel = screen.getByRole('region', { name: '进行中的订单' })
    await waitFor(() => expect(within(panel).getAllByRole('listitem')).toHaveLength(3))
    const rows = within(panel).getAllByRole('listitem')
    expect(rows.map(row => row.textContent)).toEqual([
      expect.stringContaining('商品delivery'), expect.stringContaining('商品pending'), expect.stringContaining('商品transit'),
    ])
    await userEvent.click(within(rows[1]!).getByRole('button', { name: '去支付' }))
    expect(mocks.push).toHaveBeenCalledWith('/borough-100/orders/pending')
    await userEvent.click(within(rows[0]!).getByRole('button', { name: '问问' }))
    expect(mocks.send).toHaveBeenCalledWith(expect.stringContaining('delivery'))
  })

  it('热门八个方块，低库存与机器译文标注；展开全部后按需获取目录', async () => {
    render(<HomeView {...base} popular={[{ ...popular[0]!, nameTranslationStatus: 'MACHINE' }, ...popular.slice(1)]} />)
    const section = screen.getByRole('region', { name: '本周热门' })
    expect(within(section).getAllByRole('button', { name: /商品p/ })).toHaveLength(8)
    expect(within(section).getByText('紧张')).toBeInTheDocument()
    expect(within(section).getByText('机器译文')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /全部商品/ }))
    await waitFor(() => expect(mocks.listProducts).toHaveBeenCalledWith('borough-100', 'zh-CN'))
    expect(screen.getAllByRole('button', { name: /商品p|商品extra/ })).toHaveLength(9)
    expect(screen.getByText('七天内可退货')).toBeInTheDocument()
  })

  it('空规则不出现摘要，生效优惠券展示名称；商品点击打开浮层', async () => {
    render(<HomeView {...base} store={{ ...store, rulesSummary: '' }} coupons={[{
      id: 'c1', name: '满300减30', kind: 'AMOUNT_OFF', minSpendCents: 30000,
      amountOffCents: 3000, discountBps: null, productIds: [], startsAt: '', endsAt: '',
    }]} />)
    await userEvent.click(screen.getByRole('button', { name: /全部商品/ }))
    expect(screen.queryByText('七天内可退货')).toBeNull()
    expect(screen.getByText('满300减30')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /商品p1/ }))
    expect(mocks.openPanel).toHaveBeenCalledWith('product', 'p1')
  })

  it('有对话时让位给对话视图', () => {
    mocks.messages = [{ id: 'm1' }]
    render(<HomeView {...base} thread={<p>对话内容</p>} />)
    expect(screen.getByText('对话内容')).toBeInTheDocument()
    expect(screen.queryByText('本周热门')).toBeNull()
  })
})

describe('ProductArt', () => {
  it('缺图呈现占位；有图保留尺寸、懒加载和替代文本', () => {
    const view = render(<ProductArt product={{ name: '手工靴', imageUrl: null }} size="tile" />)
    expect(screen.getByText('暂无图片')).toBeInTheDocument()
    view.rerender(<ProductArt product={{ name: '手工靴', imageUrl: '/demo/products/03.webp' }} size="thumb" />)
    const image = screen.getByRole('img', { name: '手工靴' })
    expect(image).toHaveAttribute('loading', 'lazy')
    expect(image).toHaveAttribute('width', '96')
    expect(image).toHaveAttribute('height', '96')
  })

  it('图片加载前按类目上底色；缺图仍是条纹占位；未登记类目不上色', () => {
    const view = render(<ProductArt product={{ name: '手工靴', imageUrl: '/demo/products/03.webp', category: '鞋靴' }} size="tile" />)
    expect(screen.getByRole('img', { name: '手工靴' }).parentElement).toHaveAttribute('data-cat', 'boot')
    view.rerender(<ProductArt product={{ name: '测试品', imageUrl: '/demo/products/99.webp', category: '测试类目' }} size="tile" />)
    expect(screen.getByRole('img', { name: '测试品' }).parentElement).not.toHaveAttribute('data-cat')
  })
})
