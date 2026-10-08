import { toAfterSaleChallenge, toAfterSaleDetail, toAfterSaleSummary } from './adapters/afterSales'
import { requestJson } from './client'
import { getSession } from './credentials'
import { NoSessionError } from './shopApi'
import type { components } from './generated'
import type { AfterSaleChallenge, AfterSaleDetail, AfterSaleSummary, AfterSaleType } from '@/types/afterSales'

type S = components['schemas']

function sessionId(): string {
  const session = getSession()
  if (!session) throw new NoSessionError()
  return session.sessionId
}

export interface AfterSaleCreateInput {
  clientRequestId: string
  orderId: string
  type: AfterSaleType
  orderItemIds: string[]
  reason: string
  includeConversationSummary: boolean
}

function body(input: AfterSaleCreateInput, token?: string) {
  return {
    client_request_id: input.clientRequestId, order_id: input.orderId,
    after_sale_type: input.type, order_item_ids: input.orderItemIds,
    reason: input.reason, include_conversation_summary: input.includeConversationSummary,
    ...(token ? { confirmation_token: token } : {}),
  } satisfies S['AfterSaleCreateRequest']
}

export async function previewAfterSale(input: AfterSaleCreateInput): Promise<AfterSaleChallenge> {
  const raw = await requestJson<S['AfterSaleConfirmationChallenge']>('/api/v2/shop/after-sales', {
    method: 'POST', body: body(input), sessionId: sessionId(),
  })
  return toAfterSaleChallenge(raw)
}

export async function confirmAfterSale(
  input: AfterSaleCreateInput, token: string,
): Promise<AfterSaleSummary> {
  const raw = await requestJson<S['AfterSaleSummary']>('/api/v2/shop/after-sales', {
    method: 'POST', body: body(input, token), sessionId: sessionId(),
  })
  return toAfterSaleSummary(raw)
}

export async function listAfterSales(): Promise<AfterSaleSummary[]> {
  const raw = await requestJson<S['CursorPage_AfterSaleSummary_']>(
    '/api/v2/shop/after-sales?limit=100', { sessionId: sessionId() },
  )
  return raw.items.map(toAfterSaleSummary)
}

export async function getAfterSale(id: string): Promise<AfterSaleDetail> {
  return toAfterSaleDetail(await requestJson<S['CustomerAfterSaleDetailResponse']>(
    `/api/v2/shop/after-sales/${encodeURIComponent(id)}`, { sessionId: sessionId() },
  ))
}

export async function supplementAfterSale(
  id: string, note: string, clientRequestId: string,
): Promise<AfterSaleSummary> {
  return toAfterSaleSummary(await requestJson<S['AfterSaleSummary']>(
    `/api/v2/shop/after-sales/${encodeURIComponent(id)}/supplements`, {
      method: 'POST', body: { note, client_request_id: clientRequestId }, sessionId: sessionId(),
    },
  ))
}
