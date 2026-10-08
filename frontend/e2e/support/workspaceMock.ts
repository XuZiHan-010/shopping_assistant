import type { Page } from '@playwright/test'

/**
 * 订单页与商品页（W Task 9）的 `page.route` 打桩。
 *
 * 在 `mockOpsAssistantShell()` 之后调用：Playwright 后注册的处理器优先，这里的订单列表
 * 会覆盖首页那份只有一单的固定载荷。载荷是固定演示值，只验证前端渲染与请求形状，
 * 不重新验证契约（§8.12.3、§8.12.4）。
 *
 * 订单列表按三项筛选过滤，每页 3 单；游标里记下签发时的筛选条件，拿旧游标配新筛选
 * 会得到 `422 INVALID_CURSOR`——与后端「游标绑定查询形状」同一行为（§8.7.4），
 * 并把这类请求记进 `invalidCursorRequests`，让用例断言页面从没犯过这种错。
 */

export interface E2EOrder {
  id: string
  payment: 'PENDING' | 'PAID' | 'CLOSED'
  fulfillment: 'NOT_SHIPPED' | 'SHIPPED' | 'IN_TRANSIT' | 'OUT_FOR_DELIVERY' | 'DELIVERED'
  afterSale: 'NONE' | 'ACTIVE' | 'CLOSED'
  alias: string
  item: string
  unitCents: number
  quantity: number
}

export const E2E_ORDERS: E2EOrder[] = [
  {
    id: 'order-e2e-000000000000000000000000101',
    payment: 'PAID',
    fulfillment: 'NOT_SHIPPED',
    afterSale: 'NONE',
    alias: '顾客 R5T1',
    item: '棉麻休闲衬衫',
    unitCents: 26500,
    quantity: 2,
  },
  {
    id: 'order-e2e-000000000000000000000000102',
    payment: 'PENDING',
    fulfillment: 'NOT_SHIPPED',
    afterSale: 'NONE',
    alias: '顾客 P2Q9',
    item: '帆布托特包',
    unitCents: 12000,
    quantity: 1,
  },
  {
    id: 'order-e2e-000000000000000000000000103',
    payment: 'PAID',
    fulfillment: 'IN_TRANSIT',
    afterSale: 'NONE',
    alias: '顾客 K3F9',
    item: '轻量通勤夹克',
    unitCents: 45900,
    quantity: 1,
  },
  {
    id: 'order-e2e-000000000000000000000000104',
    payment: 'PAID',
    fulfillment: 'DELIVERED',
    afterSale: 'NONE',
    alias: '顾客 M8N2',
    item: '羊毛围巾',
    unitCents: 18800,
    quantity: 1,
  },
  {
    id: 'order-e2e-000000000000000000000000105',
    payment: 'PAID',
    fulfillment: 'DELIVERED',
    afterSale: 'ACTIVE',
    alias: '顾客 Z4X7',
    item: '真皮短靴',
    unitCents: 69900,
    quantity: 1,
  },
]

const PAGE_SIZE = 3

function summary(order: E2EOrder, index: number) {
  return {
    id: order.id,
    payment_status: order.payment,
    fulfillment_status: order.fulfillment,
    after_sale_status: order.afterSale,
    total_cents: order.unitCents * order.quantity,
    item_count: order.quantity,
    created_at: `2026-09-2${3 - Math.min(index, 3)}T05:40:00Z`,
    pay_by: '2026-09-23T06:10:00Z',
    lead_item: { product_id: `product-${order.id}`, name: order.item, image_url: null },
    last_event_at: '2026-09-23T05:41:00Z',
    buyer_alias: order.alias,
    line_count: 1,
  }
}

function detail(order: E2EOrder, index: number) {
  const base = summary(order, index)
  const lineTotal = order.unitCents * order.quantity
  return {
    ...base,
    items: [
      {
        order_item_id: `${order.id}-line-1`,
        product_id: `product-${order.id}`,
        name: order.item,
        quantity: order.quantity,
        unit_price_cents: order.unitCents,
        discount_cents: 0,
        line_total_cents: lineTotal,
      },
    ],
    subtotal_cents: lineTotal,
    discount_cents: 0,
    coupon_id: null,
    paid_at: order.payment === 'PAID' ? '2026-09-23T05:45:00Z' : null,
    closed_at: null,
    close_reason: null,
    is_demo: true,
  }
}

export interface OrdersMockLog {
  listRequests: URL[]
  invalidCursorRequests: URL[]
}

export async function mockOrdersPage(page: Page): Promise<OrdersMockLog> {
  const log: OrdersMockLog = { listRequests: [], invalidCursorRequests: [] }

  await page.route('**/api/v2/merchant/orders*', async (route) => {
    const url = new URL(route.request().url())
    log.listRequests.push(url)
    const payment = url.searchParams.get('payment_status') ?? ''
    const fulfillment = url.searchParams.get('fulfillment_status') ?? ''
    const afterSale = url.searchParams.get('after_sale_status') ?? ''
    const shape = `${payment},${fulfillment},${afterSale}`
    const cursor = url.searchParams.get('cursor')

    let offset = 0
    if (cursor) {
      const [boundShape, rawOffset] = cursor.split(':')
      if (boundShape !== shape) {
        log.invalidCursorRequests.push(url)
        await route.fulfill({
          status: 422,
          json: {
            code: 'INVALID_CURSOR',
            message: '游标与当前查询不匹配',
            request_id: 'req-e2e',
            retryable: false,
            details: [],
          },
        })
        return
      }
      offset = Number(rawOffset)
    }

    const matched = E2E_ORDERS.map((order, index) => ({ order, index })).filter(
      ({ order }) =>
        (!payment || order.payment === payment) &&
        (!fulfillment || order.fulfillment === fulfillment) &&
        (!afterSale || order.afterSale === afterSale),
    )
    const slice = matched.slice(offset, offset + PAGE_SIZE)
    const more = offset + PAGE_SIZE < matched.length
    await route.fulfill({
      json: {
        items: slice.map(({ order, index }) => summary(order, index)),
        next_cursor: more ? `${shape}:${offset + PAGE_SIZE}` : null,
        has_more: more,
      },
    })
  })

  await page.route('**/api/v2/merchant/orders/*', async (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop() ?? '')
    const index = E2E_ORDERS.findIndex((order) => order.id === id)
    if (index < 0) {
      await route.fulfill({
        status: 403,
        json: {
          code: 'RESOURCE_FORBIDDEN',
          message: '无权访问',
          request_id: 'req-e2e',
          retryable: false,
          details: [],
        },
      })
      return
    }
    await route.fulfill({ json: detail(E2E_ORDERS[index]!, index) })
  })

  return log
}

export async function mockCatalogPage(page: Page): Promise<void> {
  await page.route('**/api/v2/merchant/products/content*', async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            id: 'product-e2e-000000000000000000000001',
            title: '轻量通勤夹克（M 码）',
            category: '男装',
            status: 'ONLINE',
            content_version: 4,
            missing_required_attributes: ['面料成分'],
            missing_content_fields: ['商品图片'],
            content_complete: false,
            stock_on_hand: 5,
            stock_reserved: 2,
            stock_available: 3,
          },
          {
            id: 'product-e2e-000000000000000000000002',
            title: '棉麻休闲衬衫',
            category: '男装',
            status: 'ONLINE',
            content_version: 2,
            missing_required_attributes: [],
            missing_content_fields: [],
            content_complete: true,
            stock_on_hand: 40,
            stock_reserved: 0,
            stock_available: 40,
          },
          {
            id: 'product-e2e-000000000000000000000003',
            title: '帆布托特包',
            category: '箱包',
            status: 'AUDITING',
            content_version: 1,
            missing_required_attributes: [],
            missing_content_fields: ['商品描述'],
            content_complete: false,
            stock_on_hand: 12,
            stock_reserved: 1,
            stock_available: 11,
          },
        ],
        next_cursor: null,
        has_more: false,
      },
    })
  })
}

/**
 * W Task 10 换样式的运营页（库存、待审批与审批详情、售后、顾客信号、商家记忆）的打桩。
 *
 * 在 `mockOpsAssistantShell()` 之后调用：后注册的处理器优先，这里的草稿、售后、信号
 * 列表会覆盖首页那份空列表。库存告警沿用首页的一条；商品内容沿用 `mockCatalogPage()`。
 * 文案故意偏长（长标题、长原因），用来检验 375px 下没有横向溢出。
 */
export const E2E_DRAFT_ID = 'draft-e2e-000000000000000000000000001'

export async function mockOperationsPages(page: Page): Promise<void> {
  const draft = (id: string, title: string, overrides: Record<string, unknown> = {}) => ({
    id,
    kind: 'CONTENT_CHANGE',
    state: 'STAGED',
    title,
    draft_version: 1,
    target_version: 3,
    created_at: '2026-09-23T05:40:00Z',
    updated_at: '2026-09-23T05:40:00Z',
    expires_at: '2026-09-30T05:40:00Z',
    batch_id: null,
    ...overrides,
  })

  await page.route('**/api/v2/merchant/drafts*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({
      json: {
        items: [
          draft('draft-e2e-batch-a', '补充「轻量通勤夹克（M 码）」的面料成分与洗涤说明', {
            batch_id: 'batch-e2e-0000000000000001',
          }),
          draft('draft-e2e-batch-b', '补充「帆布托特包」的商品描述', {
            batch_id: 'batch-e2e-0000000000000001',
          }),
          draft(E2E_DRAFT_ID, '补货：轻量通勤夹克（M 码）+60 件，按近 30 天销量估算', {
            kind: 'RESTOCK',
          }),
        ],
        next_cursor: null,
        has_more: false,
      },
    })
  })

  await page.route('**/api/v2/merchant/drafts/*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({
      json: {
        ...draft(E2E_DRAFT_ID, '补货：轻量通勤夹克（M 码）+60 件，按近 30 天销量估算', {
          kind: 'RESTOCK',
        }),
        diff: {
          entries: [
            {
              entry_id: `${E2E_DRAFT_ID}:stock`,
              target_type: 'PRODUCT',
              target_id: 'product-e2e-000000000000000000000001',
              field: 'stock_on_hand',
              unit: 'COUNT',
              before: 3,
              after: 63,
              is_preview: false,
            },
          ],
        },
        guardrail_checks: [
          {
            code: 'RESTOCK_QUANTITY_LIMIT',
            passed: true,
            current_limit: null,
            remediation: null,
          },
        ],
        guardrails_checked_at: '2026-09-23T05:40:00Z',
        approval_evidence: 'evidence-e2e',
        approval_evidence_expires_at: '2099-01-01T00:00:00Z',
      },
    })
  })

  await page.route('**/api/v2/merchant/coupons*', async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            id: 'coupon-e2e-1',
            name: '秋季上新九折券（全场服饰类目可用）',
            kind: 'PERCENT_OFF',
            state: 'ACTIVE',
            currently_active: true,
            min_spend_cents: 0,
            amount_off_cents: null,
            discount_bps: 9000,
            starts_at: '2026-09-01T00:00:00Z',
            ends_at: '2026-10-31T00:00:00Z',
          },
        ],
        next_cursor: null,
        has_more: false,
      },
    })
  })

  const afterSale = {
    id: 'after-sale-e2e-000000000000000000001',
    order_id: 'order-e2e-000000000000000000000000105',
    after_sale_type: 'RETURN_REFUND',
    state: 'PENDING_MERCHANT',
    refund_amount_cents: null,
    buyer_alias: '顾客 Z4X7',
    first_response_due_at: '2026-09-24T05:40:00Z',
    created_at: '2026-09-23T05:40:00Z',
  }
  await page.route('**/api/v2/merchant/after-sales*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({ json: { items: [afterSale], next_cursor: null, has_more: false } })
  })
  await page.route('**/api/v2/merchant/after-sales/*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({
      json: {
        ...afterSale,
        reason: '鞋跟处有明显划痕，与商品详情页的描述不符，希望退货退款并由商家承担运费',
        lines: [
          {
            snapshot: {
              order_item_id: 'order-item-e2e-1',
              name: '真皮短靴',
              quantity: 1,
            },
            refund_cents: 69900,
          },
        ],
        events: [
          {
            id: 'event-e2e-1',
            to_state: 'PENDING_MERCHANT',
            actor: 'CUSTOMER',
            occurred_at: '2026-09-23T05:40:00Z',
          },
        ],
        supplements: [],
        replies: [],
        conversation_summary: { status: 'NOT_SHARED', text: null, unavailable_reason: null },
      },
    })
  })

  await page.route('**/api/v2/merchant/customer-signals*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({
      json: {
        items: [
          {
            id: 'signal-e2e-1',
            kind: 'CONTENT_GAP',
            product_id: 'product-e2e-000000000000000000000001',
            product_name: '轻量通勤夹克（M 码）',
            signal_date: '2026-09-23',
            count: 7,
            is_ignored: false,
            ignore_reason: null,
          },
          {
            id: 'signal-e2e-2',
            kind: 'RETURN_REQUESTS',
            product_id: 'product-e2e-000000000000000000000002',
            product_name: '真皮短靴',
            signal_date: '2026-09-22',
            count: 3,
            is_ignored: true,
            ignore_reason: '已联系供应商更换批次，下周复查',
          },
        ],
        next_cursor: null,
        has_more: false,
      },
    })
  })

  await page.route('**/api/v2/merchant/memories*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({
      json: {
        facts: {
          items: [
            {
              id: 'memory-e2e-1',
              layer: 'FACT',
              category: 'reply_tone',
              content: '客服回复偏正式，先致歉再给出处理时限，不使用网络用语',
              source_ref: { conversation_id: 'conversation-e2e-1', message_id: 'message-e2e-1' },
              updated_at: '2026-09-23T05:40:00Z',
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        summaries: [
          {
            id: 'memory-e2e-2',
            layer: 'SUMMARY',
            category: 'reply_tone',
            content: '商家偏好正式、先致歉的客服语气',
            source_ref: null,
            updated_at: '2026-09-23T05:40:00Z',
          },
        ],
      },
    })
  })
}
