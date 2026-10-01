import { toCustomerMemories } from './adapters/memory'
import { requestJson } from './client'
import { getSession } from './credentials'
import { NoSessionError } from './shopApi'
import type { components } from './generated'
import type { CustomerMemories } from '@/types/memory'

type S = components['schemas']

function boundSessionId(): string {
  const session = getSession()
  if (!session?.isBound) throw new NoSessionError()
  return session.sessionId
}

export async function listCustomerMemories(cursor?: string): Promise<CustomerMemories> {
  const query = new URLSearchParams({ limit: '20' })
  if (cursor) query.set('cursor', cursor)
  const raw = await requestJson<S['CustomerMemoriesResponse']>(
    `/api/v2/shop/memories?${query}`, { sessionId: boundSessionId() },
  )
  return toCustomerMemories(raw)
}

export async function deleteCustomerMemory(id: string): Promise<void> {
  await requestJson<void>(`/api/v2/shop/memories/${encodeURIComponent(id)}`, {
    method: 'DELETE', sessionId: boundSessionId(),
  })
}

export async function setCustomerMemoryPreference(enabled: boolean): Promise<number> {
  const body: S['MemoryPreferenceRequest'] = enabled
    ? { enabled: true } : { enabled: false, purge_confirmation: 'yes' }
  const raw = await requestJson<S['MemoryPreferenceResponse']>('/api/v2/shop/memory-preference', {
    method: 'PUT', sessionId: boundSessionId(), body,
  })
  return raw.purged_count
}
