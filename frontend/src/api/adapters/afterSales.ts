import type { components } from '@/api/generated'
import type {
  CustomerSignal, MerchantAfterSale, MerchantAfterSaleDetail, Page,
} from '@/types/afterSales'
import { merchantRequest, queryString } from './v2Http'

type S = components['schemas']

export function toMerchantAfterSale(raw: S['MerchantAfterSaleSummary']): MerchantAfterSale {
  return {
    id: raw.id, orderId: raw.order_id, type: raw.after_sale_type,
    state: raw.state, refundAmountCents: raw.refund_amount_cents,
    buyerAlias: raw.buyer_alias, firstResponseDueAt: raw.first_response_due_at,
    createdAt: raw.created_at,
  }
}

export function toMerchantAfterSaleDetail(raw: S['MerchantAfterSaleDetailResponse']): MerchantAfterSaleDetail {
  return {
    ...toMerchantAfterSale(raw),
    reason: raw.reason,
    lines: raw.lines.map((line) => ({
      orderItemId: line.snapshot.order_item_id, name: line.snapshot.name,
      quantity: line.snapshot.quantity, refundCents: line.refund_cents,
    })),
    events: raw.events.map((event) => ({
      id: event.id, toState: event.to_state, actor: event.actor,
      occurredAt: event.occurred_at,
    })),
    supplements: raw.supplements.map((item) => ({
      id: item.id, note: item.note, submittedAt: item.submitted_at,
    })),
    replies: raw.replies.map((item) => ({
      id: item.id, text: item.text, sentAt: item.sent_at,
    })),
    conversationSummary: {
      status: raw.conversation_summary.status,
      text: raw.conversation_summary.text,
      unavailableReason: raw.conversation_summary.unavailable_reason,
    },
  }
}

export function toCustomerSignal(raw: S['CustomerSignal']): CustomerSignal {
  return {
    id: raw.id, kind: raw.kind, productId: raw.product_id,
    productName: raw.product_name, signalDate: raw.signal_date, count: raw.count,
    isIgnored: raw.is_ignored, ignoreReason: raw.ignore_reason,
  }
}

export async function fetchAfterSales(
  sessionId: string, options: { state?: string; cursor?: string; limit?: number } = {},
): Promise<Page<MerchantAfterSale>> {
  const response = await merchantRequest(
    `/api/v2/merchant/after-sales${queryString(options)}`, sessionId,
  )
  const raw = await response.json() as S['CursorPage_MerchantAfterSaleSummary_']
  return { items: raw.items.map(toMerchantAfterSale), nextCursor: raw.next_cursor, hasMore: raw.has_more }
}

export async function fetchAfterSaleDetail(
  sessionId: string, id: string,
): Promise<MerchantAfterSaleDetail> {
  const response = await merchantRequest(
    `/api/v2/merchant/after-sales/${encodeURIComponent(id)}`, sessionId,
  )
  return toMerchantAfterSaleDetail(await response.json() as S['MerchantAfterSaleDetailResponse'])
}

export async function fetchSignals(
  sessionId: string, options: { includeIgnored?: boolean; cursor?: string; limit?: number } = {},
): Promise<Page<CustomerSignal>> {
  const response = await merchantRequest(
    `/api/v2/merchant/customer-signals${queryString({
      include_ignored: options.includeIgnored ? 'true' : 'false',
      cursor: options.cursor, limit: options.limit,
    })}`, sessionId,
  )
  const raw = await response.json() as S['CursorPage_CustomerSignal_']
  return { items: raw.items.map(toCustomerSignal), nextCursor: raw.next_cursor, hasMore: raw.has_more }
}

export async function ignoreSignal(
  sessionId: string, id: string, reason: string, clientRequestId: string,
): Promise<CustomerSignal> {
  const response = await merchantRequest(
    `/api/v2/merchant/customer-signals/${encodeURIComponent(id)}/ignore`, sessionId,
    { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason, client_request_id: clientRequestId }) },
  )
  return toCustomerSignal(await response.json() as S['CustomerSignal'])
}
