import type { Page } from '@playwright/test'

/**
 * v2 商家端点的 `page.route` 共用打桩层。
 *
 * v2 商家会话/聊天走裸 `fetch`（`/api/v2/merchant/*`），不经过 v1 的
 * `resolveTransport()` Mock 传输层（`src/api/mock/transport.ts`），因此常规
 * Mock E2E 套件此前从未覆盖过它——两页合并（2026-09-27）删除
 * `conversation.spec.ts`/`localization.spec.ts` 时的结论就是"重建这些场景
 * 需要先补一套类似 `mock/transport.ts` 的通用 fetch 拦截层"。
 *
 * 本模块就是那层，但刻意做得比 v1 的版本传输层薄：不做请求方法分发表、
 * 不做 fixture 索引匹配，只按测试场景需要的端点逐个注册 `page.route`——
 * v2 Chat 的载荷形状（`MerchantChatResponse`）本身已经很稳定（契约 §8.7），
 * 测试要验证的是前端如何渲染这份数据，不是重新验证契约本身。
 *
 * 每个 `mockX` 函数可重复调用以覆盖前一次注册（Playwright `page.route` 后
 * 注册的处理器优先），方便同一测试内先给默认态再在某一步换成另一种响应。
 */

export const DEMO_MERCHANT_A = { merchantId: 'merchant-a', displayName: 'Borough商家100' }
export const DEMO_MERCHANT_B = { merchantId: 'merchant-b', displayName: 'Borough商家101' }

/** `GET /api/demo/merchants`——v1/v2 共用的公开演示身份入口，商家切换器数据源。 */
export async function mockDemoMerchants(
  page: Page,
  merchants: Array<{ merchantId: string; displayName: string }> = [
    DEMO_MERCHANT_A,
    DEMO_MERCHANT_B,
  ],
): Promise<void> {
  await page.route('**/api/demo/merchants', async (route) => {
    await route.fulfill({
      json: {
        merchants: merchants.map((m) => ({
          merchant_id: m.merchantId,
          display_name: m.displayName,
          token: `demo-token-${m.merchantId}`,
        })),
      },
    })
  })
}

const DEFAULT_MOCK_SESSION_ID = 'e2e-mock-session-000000000000000000000000'

/**
 * 某个演示 Token 在 Mock 里换到的会话 ID（W Task 11）。`mockMerchantSession()` 按 Bearer
 * Token 发不同的会话 ID，让按 `X-Session-Id` 分桶的 Mock（如会话目录）能区分切换前后的商家。
 *
 * 注意 Mock E2E 下 `/api/demo/merchants` 由前端 Mock 传输层直接返回
 * `src/api/mock/scenarios.ts::MOCK_MERCHANTS`（`demo-token-100` / `-101` / `-102`），
 * 不经过 `mockDemoMerchants()` 的路由；按商家分桶时请用 `MOCK_DEMO_TOKENS`。
 */
export function mockSessionIdFor(demoToken: string): string {
  return `e2e-mock-session-${demoToken}`
}

/** Mock 传输层演示商家（显示名 → Token），与 `MOCK_MERCHANTS` 一致。 */
export const MOCK_DEMO_TOKENS = {
  Borough商家100: 'demo-token-100',
  Borough商家101: 'demo-token-101',
} as const

/** Mock 会话响应里的店铺标识；「顾客视角」链接 = `MOCK_SHOP_BASE_URL` + `/` + 它（D-N5-4）。 */
export const MOCK_SHOP_SLUG = 'borough-demo-100'
/** 与 `scripts/mock-e2e-server.mjs` 注入的 `VITE_SHOP_BASE_URL` 一致。 */
export const MOCK_SHOP_BASE_URL = 'https://shop.e2e.example'

/**
 * `POST /api/v2/merchant/sessions`——返回一个不过期的会话，测试不关心真实 TTL。
 * 会话 ID 按 Bearer Token 区分（见 `mockSessionIdFor`）；没有 Bearer 时沿用固定默认值。
 */
export async function mockMerchantSession(
  page: Page,
  merchantDisplayName: string = DEMO_MERCHANT_A.displayName,
): Promise<void> {
  await page.route('**/api/v2/merchant/sessions', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const bearer = /^Bearer (.+)$/.exec(route.request().headers()['authorization'] ?? '')
    await route.fulfill({
      status: 201,
      json: {
        session_id: bearer ? mockSessionIdFor(bearer[1]) : DEFAULT_MOCK_SESSION_ID,
        role: 'MERCHANT',
        expires_at: '2099-01-01T00:00:00Z',
        merchant_display_name: merchantDisplayName,
        shop_slug: MOCK_SHOP_SLUG,
      },
    })
  })
}

export interface ConversationFixture {
  id: string
  title: string
  createdAt?: string
  updatedAt?: string
}

/**
 * `GET /api/v2/merchant/conversations`——会话目录列表，固定一页、不分页。
 *
 * 传 `options.ownerToken` 时目录只属于用该演示 Token 登录的商家：请求的 `X-Session-Id`
 * 不是 `mockSessionIdFor(ownerToken)` 就返回空目录，与真实后端按会话隔离一致
 * （切换商家后重新拉取目录，不会再拿回上一个商家的会话）。
 */
export async function mockConversationList(
  page: Page,
  items: ConversationFixture[] = [],
  options: { ownerToken?: string } = {},
): Promise<void> {
  await page.route('**/api/v2/merchant/conversations*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const sessionId = route.request().headers()['x-session-id'] ?? ''
    const owned =
      options.ownerToken === undefined || sessionId === mockSessionIdFor(options.ownerToken)
    await route.fulfill({
      json: {
        items: (owned ? items : []).map((item) => ({
          id: item.id,
          title: item.title,
          created_at: item.createdAt ?? '2026-01-01T00:00:00Z',
          updated_at: item.updatedAt ?? '2026-01-01T00:00:00Z',
        })),
        next_cursor: null,
        has_more: false,
      },
    })
  })
}

/** `DELETE /api/v2/merchant/conversations/{id}`——固定成功，调用方按需断言请求是否发生。 */
export async function mockDeleteConversation(page: Page): Promise<void> {
  await page.route('**/api/v2/merchant/conversations/*', async (route) => {
    if (route.request().method() !== 'DELETE') return route.fallback()
    await route.fulfill({ status: 204, body: '' })
  })
}

export interface MessageFixture {
  id: string
  role: 'user' | 'assistant'
  content: string
  turn?: ChatTurnFixture
}

/** `GET /api/v2/merchant/conversations/{id}`——打开历史对话时的完整明细。 */
export async function mockConversationDetail(
  page: Page,
  conversationId: string,
  conversation: ConversationFixture,
  messages: MessageFixture[],
): Promise<void> {
  await page.route(`**/api/v2/merchant/conversations/${conversationId}*`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({
      json: {
        conversation: {
          id: conversation.id,
          title: conversation.title,
          created_at: conversation.createdAt ?? '2026-01-01T00:00:00Z',
          updated_at: conversation.updatedAt ?? '2026-01-01T00:00:00Z',
        },
        messages: {
          items: messages.map((message, index) => ({
            id: message.id,
            role: message.role,
            content: message.content,
            created_at: '2026-01-01T00:00:00Z',
            answer: message.turn ? buildMerchantChatResponse(message.turn, String(index)) : null,
            feedback: null,
          })),
          next_cursor: null,
          has_more: false,
        },
      },
    })
  })
}

/** 契约 `PublicToolSummary`：工具行只能显示这几句固定短句，不接受任意正文。 */
type PublicToolSummary =
  | '正在处理'
  | '处理完成'
  | '暂时不可用'
  | '处理失败'
  | 'Processing'
  | 'Completed'
  | 'Unavailable'
  | 'Failed'

export interface ChatTurnFixture {
  answer: string
  answerMode?: 'METRIC' | 'DETAIL' | 'RULE' | 'IDENTITY' | 'CHAT' | 'INVALID'
  conversationId?: string
  degraded?: boolean
  degradedReason?: string | null
  suggestions?: string[]
  toolCalls?: Array<{ toolName: string; callId: string; summary: PublicToolSummary }>
  visualization?: {
    enabled: boolean
    type?: 'LINE' | 'BAR' | 'PIE'
    title?: string
    unit?: string
    data?: Array<{ label: string; value: number }>
  }
}

function buildMerchantChatResponse(turn: ChatTurnFixture, requestId: string) {
  // 契约 `AnalysisSource`（`docs/backend-development-plan.md` §8.7.6）：
  // DATABASE/KNOWLEDGE/ATTACHMENT/MEMORY/FALLBACK/NONE。CHAT/INVALID 只能是
  // NONE；其余模式用 DATABASE（指标/明细/身份）或 KNOWLEDGE（规则）近似即可
  // ——E2E 只验证前端渲染路径，不重新验证契约本身允许的来源分层。
  const analysisSource =
    turn.answerMode === 'METRIC' || turn.answerMode === 'DETAIL' || turn.answerMode === 'IDENTITY'
      ? 'DATABASE'
      : turn.answerMode === 'RULE'
        ? 'KNOWLEDGE'
        : 'NONE'
  return {
    id: `answer-${requestId}`,
    conversation_id: turn.conversationId ?? 'conv-mock-000000000000000000000000',
    answer: turn.answer,
    answer_mode: turn.answerMode ?? 'CHAT',
    tool_calls: (turn.toolCalls ?? []).map((call) => ({
      tool_name: call.toolName,
      call_id: call.callId,
      status: 'SUCCEEDED',
      summary: call.summary,
    })),
    created_at: '2026-01-01T00:00:00Z',
    suggestions: turn.suggestions ?? [],
    suggestion_alternates: [],
    analysis_sources: [
      {
        source: analysisSource,
        degraded: Boolean(turn.degraded),
        degraded_reason: turn.degraded ? (turn.degradedReason ?? '演示降级') : null,
      },
    ],
    thinking_steps: [],
    quality_status: 'PASSED',
    quality_attempts: 1,
    quality_notes: [],
    degraded: Boolean(turn.degraded),
    degraded_reason: turn.degraded ? (turn.degradedReason ?? '演示降级') : null,
    visualization: turn.visualization
      ? {
          enabled: turn.visualization.enabled,
          type: turn.visualization.type ?? null,
          allowed_types: turn.visualization.enabled ? ['LINE', 'BAR', 'PIE'] : [],
          title: turn.visualization.title ?? null,
          dimension_key: null,
          metric_key: null,
          unit: turn.visualization.unit ?? null,
          data: turn.visualization.data ?? [],
        }
      : {
          enabled: false,
          type: null,
          allowed_types: [],
          title: null,
          dimension_key: null,
          metric_key: null,
          unit: null,
          data: [],
        },
  }
}

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

/**
 * `POST /api/v2/merchant/chat`——按调用顺序逐轮返回 `turns` 里的固定回答，
 * 每轮都是一次性 SSE 流（只含 `turn_complete`，不模拟 `step`/`tool_call`
 * 中间事件——组件对中间事件的渲染已由 Vitest 组件测试覆盖，浏览器 E2E
 * 只需要验证首屏可达与端到端渲染路径本身）。
 */
export async function mockMerchantChat(page: Page, turns: ChatTurnFixture[]): Promise<void> {
  let callIndex = 0
  await page.route('**/api/v2/merchant/chat', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const turn = turns[Math.min(callIndex, turns.length - 1)]
    callIndex += 1
    const payload = buildMerchantChatResponse(turn, String(callIndex))
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: sseFrame('turn_complete', payload),
    })
  })
}

/** `POST /api/v2/merchant/answers/{id}/feedback`——固定按请求体回显最终状态。 */
export async function mockMerchantFeedback(page: Page): Promise<void> {
  await page.route('**/api/v2/merchant/answers/*/feedback', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON() as {
      kind: 'ADOPTION' | 'REACTION'
      adopted?: boolean
      reaction?: 'LIKE' | 'DISLIKE' | null
      reason?: string
    }
    await route.fulfill({
      json: {
        adopted: body.kind === 'ADOPTION' ? Boolean(body.adopted) : false,
        reaction: body.kind === 'REACTION' ? (body.reaction ?? null) : null,
        reason: body.reason ?? null,
      },
    })
  })
}

/** 一次性注册运营助手首屏所需的最小端点集合（会话 + 空会话目录 + 首页只读端点）。 */
export async function mockOpsAssistantShell(
  page: Page,
  options: { merchantDisplayName?: string } = {},
): Promise<void> {
  await mockDemoMerchants(page)
  await mockMerchantSession(page, options.merchantDisplayName)
  await mockConversationList(page)
  await mockHomeEndpoints(page)
}

/**
 * 首页（W Task 8）空闲后才发的七个只读端点：简报、草稿、主指标、库存告警、售后、信号、订单。
 *
 * W 阶段起 `/` 是首页，任何从 `/` 进入的用例都会在空闲后触发这些请求；不打桩时它们打到
 * 不存在的后端，控制台出现资源加载错误，也让窄屏溢出检查只覆盖到“不可用”空态。
 * 载荷是固定的演示值，只用于验证前端渲染路径，不重新验证契约（§8.12.4）。
 */
export async function mockHomeEndpoints(page: Page): Promise<void> {
  const emptyPage = { items: [], next_cursor: null, has_more: false }
  const envelope = {
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    thinking_steps: [],
    quality_status: 'NOT_RUN',
    quality_attempts: 0,
    quality_notes: [],
    degraded: false,
    degraded_reason: null,
  }
  await page.route('**/api/v2/merchant/briefs/daily/current', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({
      json: {
        ...envelope,
        brief_version: 1,
        business_date: '2026-09-23',
        business_timezone: 'Asia/Shanghai',
        data_as_of: '2026-09-23T00:00:00Z',
        generated_at: '2026-09-23T00:05:00Z',
        trigger: 'SCHEDULED',
        items: [
          {
            rank: 1,
            kind: 'INVENTORY_ALERT',
            title: '库存偏低：轻量通勤夹克（M 码）',
            evidence: '可售 3 件，低于阈值 5 件；近 30 天售出 58 件。',
            amount_cents: null,
            next_action_prompt: '给「轻量通勤夹克」起草补货',
          },
        ],
        collapsed_count: 0,
      },
    })
  })
  await page.route('**/api/v2/merchant/drafts*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({ json: emptyPage })
  })
  await page.route('**/api/v2/merchant/metrics/overview', async (route) => {
    await route.fulfill({
      json: {
        ...envelope,
        business_timezone: 'Asia/Shanghai',
        data_as_of: '2026-09-23T04:00:00Z',
        source: 'MIXED',
        definition_version: 'net_gmv@2026-09',
        current_period: { start: '2026-09-21', end: '2026-09-23', label: '本周前 3 天' },
        baseline_period: { start: '2026-09-14', end: '2026-09-16', label: '上周同期 3 天' },
        headline: {
          metric_code: 'net_gmv',
          current_cents: 1234500,
          baseline_cents: 1300000,
          change_ratio_bp: -504,
          current_series: [
            { date: '2026-09-21', value_cents: 400000 },
            { date: '2026-09-22', value_cents: 434500 },
            { date: '2026-09-23', value_cents: 400000 },
          ],
          baseline_series: [
            { date: '2026-09-14', value_cents: 450000 },
            { date: '2026-09-15', value_cents: 450000 },
            { date: '2026-09-16', value_cents: 400000 },
          ],
        },
        attribution: {
          dimension: 'category',
          mode: 'ABSOLUTE_CONTRIBUTION',
          segments: [
            {
              name: '男装',
              current_cents: 300000,
              baseline_cents: 371200,
              contribution_cents: -71200,
              share_bp: null,
            },
            {
              name: '鞋靴',
              current_cents: 200000,
              baseline_cents: 178900,
              contribution_cents: 21100,
              share_bp: null,
            },
          ],
          remaining_count: 0,
          remaining_contribution_cents: 0,
          stopped_reason: null,
        },
        secondary: [
          { metric_code: 'order_count', unit: 'COUNT', current_value: 86, baseline_value: 91 },
          {
            metric_code: 'refund_amount',
            unit: 'CENTS',
            current_value: 45900,
            baseline_value: 12000,
          },
          {
            metric_code: 'return_rate',
            unit: 'RATIO_BP',
            current_value: 1235,
            baseline_value: null,
          },
        ],
      },
    })
  })
  await page.route('**/api/v2/merchant/inventory/alerts*', async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            id: 'alert-e2e-1',
            kind: 'LOW_STOCK',
            product_id: 'product-e2e-1',
            product_name: '轻量通勤夹克（M 码）',
            stock_on_hand: 3,
            stock_reserved: 0,
            stock_available: 3,
            low_stock_threshold: 5,
            sold_last_30d: 58,
            days_of_supply: 1.5,
          },
        ],
        next_cursor: null,
        has_more: false,
      },
    })
  })
  await page.route('**/api/v2/merchant/after-sales*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({ json: emptyPage })
  })
  await page.route('**/api/v2/merchant/customer-signals*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({ json: emptyPage })
  })
  await page.route('**/api/v2/merchant/orders*', async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            id: 'order-e2e-000000000000000000000000001',
            payment_status: 'PAID',
            fulfillment_status: 'NOT_SHIPPED',
            after_sale_status: 'NONE',
            total_cents: 53000,
            item_count: 2,
            created_at: '2026-09-23T05:40:00Z',
            pay_by: '2026-09-23T06:10:00Z',
            lead_item: { product_id: 'product-e2e-2', name: '棉麻休闲衬衫', image_url: null },
            last_event_at: '2026-09-23T05:41:00Z',
            buyer_alias: '顾客 R5T1',
            line_count: 2,
          },
        ],
        next_cursor: null,
        has_more: false,
      },
    })
  })
}
