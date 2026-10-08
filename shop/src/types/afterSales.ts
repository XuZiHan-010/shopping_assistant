export type AfterSaleType = 'RETURN_REFUND' | 'REFUND_ONLY' | 'TICKET'
export type AfterSaleState =
  | 'PENDING_MERCHANT' | 'APPROVED' | 'REJECTED' | 'AWAITING_RETURN'
  | 'RECEIVED' | 'REFUNDED' | 'AWAITING_CUSTOMER_INFO' | 'CLOSED'

export interface AfterSaleSummary {
  id: string
  orderId: string
  type: AfterSaleType
  state: AfterSaleState
  refundAmountCents: number | null
  createdAt: string
  updatedAt: string
}

export interface AfterSaleChallenge {
  token: string
  expiresAt: string
  lines: { orderItemId: string; name: string; quantity: number; lineTotalCents: number }[]
  estimatedRefundCents: number | null
  reason: string
  summaryStatus: 'NOT_SHARED' | 'INCLUDED' | 'UNAVAILABLE'
  conversationSummary: string | null
}

export interface AfterSaleDetail extends AfterSaleSummary {
  reason: string
  lines: { orderItemId: string; name: string; quantity: number; refundCents: number }[]
  events: { id: string; toState: AfterSaleState; actor: 'CUSTOMER' | 'MERCHANT' | 'SYSTEM'; occurredAt: string }[]
  supplements: { id: string; note: string; submittedAt: string }[]
  replies: { id: string; text: string; sentAt: string }[]
  conversationSummaryShared: boolean
}
