import type { components } from '../generated'
import type { CustomerMemories, CustomerMemory } from '@/types/memory'

type S = components['schemas']

export function toCustomerMemory(raw: S['CustomerMemoryItem']): CustomerMemory {
  return {
    id: raw.id, shopSlug: raw.shop_slug, category: raw.category,
    key: raw.key, value: raw.value, lastConfirmedAt: raw.last_confirmed_at,
    expiresAt: raw.expires_at,
  }
}

export function toCustomerMemories(raw: S['CustomerMemoriesResponse']): CustomerMemories {
  return {
    memoryEnabled: raw.memory_enabled,
    items: raw.memories.items.map(toCustomerMemory),
    nextCursor: raw.memories.next_cursor,
  }
}
