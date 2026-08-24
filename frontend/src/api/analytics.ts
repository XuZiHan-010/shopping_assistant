import type { components } from '@/api/generated'
import type { ChatBiCategoryRow, ChatBiOverview } from '@/types/analytics'

import { toChatBiCategories, toChatBiOverview } from './adapters/analytics'
import { resolveTransport } from './transport'

export interface ChatBiWindow {
  startDate: string
  endDate: string
}

function toQuery(window: ChatBiWindow): string {
  return new URLSearchParams({
    start_date: window.startDate,
    end_date: window.endDate,
  }).toString()
}

export async function getChatBiOverview(
  window: ChatBiWindow,
  signal: AbortSignal,
): Promise<ChatBiOverview> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/admin/analytics/chatbi/overview?${toQuery(window)}`,
      method: 'GET',
      auth: 'admin',
    },
    signal,
  )
  return toChatBiOverview(
    (await response.json()) as components['schemas']['ChatBiOverviewResponse'],
  )
}

export async function getChatBiCategories(
  window: ChatBiWindow,
  signal: AbortSignal,
): Promise<ChatBiCategoryRow[]> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/admin/analytics/chatbi/categories?${toQuery(window)}`,
      method: 'GET',
      auth: 'admin',
    },
    signal,
  )
  return toChatBiCategories(
    (await response.json()) as components['schemas']['ChatBiCategoriesResponse'],
  )
}

export async function triggerChatBiRollup(
  window: ChatBiWindow,
  signal: AbortSignal,
): Promise<number> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: '/api/admin/analytics/chatbi/rollup',
      method: 'POST',
      auth: 'admin',
      body: { start_date: window.startDate, end_date: window.endDate },
    },
    signal,
  )
  const payload = (await response.json()) as components['schemas']['ChatBiRollupResponse']
  return payload.rows_written
}
