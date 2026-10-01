/**
 * 首页（W Task 8）组件测试共用的后端原始载荷。
 *
 * 只供 `*.spec.ts` 引用，应用代码不导入它，因此不会进入构建产物。形状按
 * `generated.ts` 的原始 schema 书写（snake_case），让测试经过真实 Adapter，
 * 而不是直接喂领域类型——Adapter 的字段映射一并被覆盖到。
 */
import type { components } from '@/api/generated'

type S = components['schemas']

export function overviewPayload(
  overrides: Partial<S['MerchantMetricsOverviewResponse']> = {},
): S['MerchantMetricsOverviewResponse'] {
  return {
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    thinking_steps: [],
    quality_status: 'NOT_RUN',
    quality_attempts: 0,
    quality_notes: [],
    degraded: false,
    degraded_reason: null,
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
        {
          name: '家居',
          current_cents: 150000,
          baseline_cents: 160000,
          contribution_cents: -10000,
          share_bp: null,
        },
        {
          name: '美妆',
          current_cents: 120000,
          baseline_cents: 126000,
          contribution_cents: -6000,
          share_bp: null,
        },
        {
          name: '食品',
          current_cents: 90000,
          baseline_cents: 93000,
          contribution_cents: -3000,
          share_bp: null,
        },
      ],
      remaining_count: 3,
      remaining_contribution_cents: 3600,
      stopped_reason: null,
    },
    secondary: [
      { metric_code: 'order_count', unit: 'COUNT', current_value: 86, baseline_value: 91 },
      { metric_code: 'refund_amount', unit: 'CENTS', current_value: 45900, baseline_value: 12000 },
      { metric_code: 'return_rate', unit: 'RATIO_BP', current_value: 1235, baseline_value: 800 },
    ],
    ...overrides,
  }
}

export function briefPayload(
  overrides: Partial<S['DailyBriefResponse']> = {},
): S['DailyBriefResponse'] {
  return {
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    thinking_steps: [],
    quality_status: 'NOT_RUN',
    quality_attempts: 0,
    quality_notes: [],
    degraded: false,
    degraded_reason: null,
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
        title: '已售罄：测试商品',
        evidence: '商品 p-1：在库 0',
        amount_cents: null,
        next_action_prompt: '给「测试商品」起草一份补货草稿',
      },
    ],
    collapsed_count: 0,
    ...overrides,
  }
}

export function page<T>(items: T[], hasMore = false) {
  return { items, next_cursor: hasMore ? 'cursor-next' : null, has_more: hasMore }
}

export function draftSummary(id: string, title: string): S['DraftSummary'] {
  return {
    id,
    kind: 'RESTOCK',
    state: 'STAGED',
    title,
    draft_version: 1,
    target_version: 3,
    batch_id: null,
    created_at: '2026-09-23T01:00:00Z',
    updated_at: '2026-09-23T01:00:00Z',
    expires_at: '2026-09-30T01:00:00Z',
  }
}

export function inventoryAlert(
  id: string,
  kind: S['InventoryAlert']['kind'],
  productName: string,
  overrides: Partial<S['InventoryAlert']> = {},
): S['InventoryAlert'] {
  return {
    id,
    kind,
    product_id: `p-${id}`,
    product_name: productName,
    stock_on_hand: kind === 'OUT_OF_STOCK' ? 0 : 3,
    stock_reserved: 0,
    stock_available: kind === 'OUT_OF_STOCK' ? 0 : 3,
    low_stock_threshold: 5,
    sold_last_30d: 58,
    days_of_supply: kind === 'OUT_OF_STOCK' ? 0 : 1.5,
    ...overrides,
  }
}

export function afterSaleSummary(
  id: string,
  state: S['MerchantAfterSaleSummary']['state'] = 'PENDING_MERCHANT',
): S['MerchantAfterSaleSummary'] {
  return {
    id,
    order_id: `order-${id}`,
    after_sale_type: 'RETURN_REFUND',
    state,
    refund_amount_cents: 45900,
    buyer_alias: '顾客 K3F9',
    first_response_due_at: '2026-09-23T10:00:00Z',
    created_at: '2026-09-23T02:00:00Z',
    updated_at: '2026-09-23T02:00:00Z',
  }
}

export function customerSignal(
  id: string,
  kind: S['CustomerSignal']['kind'],
  productName: string | null,
  overrides: Partial<S['CustomerSignal']> = {},
): S['CustomerSignal'] {
  return {
    id,
    kind,
    product_id: productName ? `p-${id}` : null,
    product_name: productName,
    signal_date: '2026-09-22',
    count: 12,
    derived_from: [],
    is_ignored: false,
    ignore_reason: null,
    ...overrides,
  }
}

export function orderSummary(
  id: string,
  overrides: Partial<S['MerchantOrderSummary']> = {},
): S['MerchantOrderSummary'] {
  return {
    id,
    payment_status: 'PAID',
    fulfillment_status: 'NOT_SHIPPED',
    after_sale_status: 'NONE',
    total_cents: 53000,
    item_count: 2,
    created_at: '2026-09-23T05:40:00Z',
    pay_by: '2026-09-23T06:10:00Z',
    lead_item: { product_id: `p-${id}`, name: '棉麻休闲衬衫', image_url: null },
    last_event_at: '2026-09-23T05:41:00Z',
    buyer_alias: '顾客 R5T1',
    line_count: 2,
    ...overrides,
  }
}

export function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

export function errorResponse(status = 503, code = 'DATA_SOURCE_UNAVAILABLE'): Response {
  return jsonResponse(
    { code, message: '数据源暂时不可用', request_id: 'req-test', retryable: true, details: [] },
    status,
  )
}
