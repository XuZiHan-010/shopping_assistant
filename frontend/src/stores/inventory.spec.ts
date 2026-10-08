import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'

import { useAuthStore } from './auth'
import { useInventoryStore } from './inventory'

const BASE_URL = 'http://127.0.0.1:8000'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function alert(overrides: Record<string, unknown> = {}) {
  return {
    id: 'LOW_STOCK:p-1',
    kind: 'LOW_STOCK',
    product_id: 'p-1',
    product_name: '测试商品',
    stock_on_hand: 6,
    stock_reserved: 2,
    stock_available: 4,
    low_stock_threshold: 5,
    sold_last_30d: 12,
    days_of_supply: 10,
    ...overrides,
  }
}

async function openTestSession(): Promise<void> {
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  const auth = useAuthStore()
  await auth.loadMerchants()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValueOnce(
      jsonResponse({
        session_id: 'sid'.padEnd(43, '0'),
        role: 'MERCHANT',
        expires_at: '2026-09-24T00:00:00Z',
        merchant_display_name: 'Borough商家100',
      }),
    ),
  )
  await auth.openSession(auth.merchants[0]!)
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('useInventoryStore', () => {
  it('loadAlerts 通过会话重试机制拉取库存告警', async () => {
    await openTestSession()
    const store = useInventoryStore()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ items: [alert()], next_cursor: null, has_more: false })),
    )

    await store.loadAlerts()

    expect(store.items).toHaveLength(1)
    expect(store.items[0]!.productName).toBe('测试商品')
  })

  it('切换商家会话时库存列表被清空', async () => {
    await openTestSession()
    const store = useInventoryStore()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ items: [alert()], next_cursor: null, has_more: false })),
    )
    await store.loadAlerts()
    expect(store.items).toHaveLength(1)

    const auth = useAuthStore()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(new Response(null, { status: 204 }))
        .mockResolvedValueOnce(
          jsonResponse({
            session_id: 'sid-2'.padEnd(43, '0'),
            role: 'MERCHANT',
            expires_at: '2026-09-24T00:00:00Z',
            merchant_display_name: 'Borough商家101',
          }),
        ),
    )
    await auth.selectAndOpenSession(auth.merchants[1]!)

    expect(store.items).toHaveLength(0)
  })
})
