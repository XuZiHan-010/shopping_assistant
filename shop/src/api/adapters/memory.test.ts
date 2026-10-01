import { expect, it } from 'vitest'
import type { components } from '../generated'
import { toCustomerMemories } from './memory'

it('maps the public memory contract without internal identities', () => {
  const raw: components['schemas']['CustomerMemoriesResponse'] = {
    memory_enabled: true,
    memories: { items: [{
      id: 'f-1', shop_slug: 'borough-api-100', category: 'style',
      key: 'color', value: '喜欢素色',
      last_confirmed_at: '2026-09-28T00:00:00Z',
      expires_at: '2027-03-27T00:00:00Z',
    }], next_cursor: null, has_more: false },
  }
  const mapped = toCustomerMemories(raw)
  expect(mapped.items[0]?.shopSlug).toBe('borough-api-100')
  expect(mapped.items[0]?.expiresAt).toBe('2027-03-27T00:00:00Z')
  expect(JSON.stringify(mapped)).not.toMatch(/buyer_key|merchant_id/)
})
