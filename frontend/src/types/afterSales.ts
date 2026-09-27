export interface Page<T> {
  items: T[]
  nextCursor: string | null
  hasMore: boolean
}

export type AfterSaleState =
  | 'PENDING_MERCHANT' | 'APPROVED' | 'REJECTED' | 'AWAITING_RETURN'
  | 'RECEIVED' | 'REFUNDED' | 'AWAITING_CUSTOMER_INFO' | 'CLOSED'

export interface MerchantAfterSale {
  id: string
  orderId: string
  type: 'RETURN_REFUND' | 'REFUND_ONLY' | 'TICKET'
  state: AfterSaleState
  refundAmountCents: number | null
  buyerAlias: string
  firstResponseDueAt: string
  createdAt: string
}

export interface MerchantAfterSaleDetail extends MerchantAfterSale {
  reason: string
  lines: { orderItemId: string; name: string; quantity: number; refundCents: number }[]
  events: { id: string; toState: AfterSaleState; actor: string; occurredAt: string }[]
  supplements: { id: string; note: string; submittedAt: string }[]
  replies: { id: string; text: string; sentAt: string }[]
  conversationSummary: { status: 'NOT_SHARED' | 'AVAILABLE' | 'UNAVAILABLE'; text: string | null; unavailableReason: string | null }
}

export interface CustomerSignal {
  id: string
  kind: 'RETURN_REQUESTS' | 'REFUND_REQUESTS' | 'SUPPORT_TICKETS' | 'CONTENT_GAP'
  productId: string | null
  productName: string | null
  signalDate: string
  count: number
  isIgnored: boolean
  ignoreReason: string | null
}
