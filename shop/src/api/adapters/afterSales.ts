import type { components } from '../generated'
import type { AfterSaleChallenge, AfterSaleDetail, AfterSaleSummary } from '@/types/afterSales'

type S = components['schemas']

export function toAfterSaleSummary(raw: S['AfterSaleSummary']): AfterSaleSummary {
  return {
    id: raw.id, orderId: raw.order_id, type: raw.after_sale_type, state: raw.state,
    refundAmountCents: raw.refund_amount_cents,
    createdAt: raw.created_at, updatedAt: raw.updated_at,
  }
}

export function toAfterSaleChallenge(raw: S['AfterSaleConfirmationChallenge']): AfterSaleChallenge {
  return {
    token: raw.confirmation_token, expiresAt: raw.expires_at,
    lines: raw.summary.lines.map((line) => ({
      orderItemId: line.order_item_id, name: line.name,
      quantity: line.quantity, lineTotalCents: line.line_total_cents,
    })),
    estimatedRefundCents: raw.summary.estimated_refund_cents,
    reason: raw.summary.reason,
    summaryStatus: raw.summary.conversation_summary_status,
    conversationSummary: raw.summary.conversation_summary,
  }
}

export function toAfterSaleDetail(raw: S['CustomerAfterSaleDetailResponse']): AfterSaleDetail {
  return {
    ...toAfterSaleSummary(raw),
    reason: raw.reason,
    lines: raw.lines.map((line) => ({
      orderItemId: line.snapshot.order_item_id,
      name: line.snapshot.name,
      quantity: line.snapshot.quantity,
      refundCents: line.refund_cents,
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
    conversationSummaryShared: raw.conversation_summary_shared,
  }
}
