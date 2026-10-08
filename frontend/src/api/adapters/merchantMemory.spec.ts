import { expect, it } from 'vitest'
import type { components } from '@/api/generated'
import { toMerchantMemories } from './merchantMemory'

it('adapts fact source and read-only summaries', () => {
  const raw: components['schemas']['MerchantMemoriesResponse'] = {
    facts: { items: [{
      id: 'f-1', layer: 'FACT', category: 'tone', content: '正式',
      source_ref: { conversation_id: 'c-1', message_id: 'm-1' },
      updated_at: '2026-09-28T00:00:00Z',
    }], next_cursor: null, has_more: false },
    summaries: [{
      id: 's-1', layer: 'SUMMARY', category: 'tone', content: '正式',
      source_ref: null, updated_at: '2026-09-28T00:00:00Z',
    }],
  }
  const result = toMerchantMemories(raw)
  expect(result.facts[0]?.sourceRef).toEqual({ conversationId: 'c-1', messageId: 'm-1' })
  expect(result.summaries[0]?.sourceRef).toBeNull()
})
