import type { components } from '@/api/generated'
import type { MerchantMemories, MerchantMemory } from '@/types/memory'
import { merchantRequest, queryString } from './v2Http'

type S = components['schemas']

export function toMerchantMemory(raw: S['MerchantMemoryItem']): MerchantMemory {
  return {
    id: raw.id, layer: raw.layer, category: raw.category,
    content: raw.content, updatedAt: raw.updated_at,
    sourceRef: raw.source_ref && {
      conversationId: raw.source_ref.conversation_id,
      messageId: raw.source_ref.message_id,
    },
  }
}

export function toMerchantMemories(raw: S['MerchantMemoriesResponse']): MerchantMemories {
  return {
    facts: raw.facts.items.map(toMerchantMemory),
    nextCursor: raw.facts.next_cursor,
    summaries: raw.summaries.map(toMerchantMemory),
  }
}

export async function fetchMerchantMemories(sessionId: string, cursor?: string): Promise<MerchantMemories> {
  const response = await merchantRequest(
    `/api/v2/merchant/memories${queryString({ cursor, limit: 20 })}`, sessionId,
  )
  return toMerchantMemories(await response.json() as S['MerchantMemoriesResponse'])
}

export async function deleteMerchantMemory(
  sessionId: string, id: string,
): Promise<S['MerchantMemoryDeleteResponse']> {
  const response = await merchantRequest(
    `/api/v2/merchant/memories/${encodeURIComponent(id)}`, sessionId, { method: 'DELETE' },
  )
  return await response.json() as S['MerchantMemoryDeleteResponse']
}
