import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'

import { useAuthStore } from './auth'
import { useCatalogOpsStore } from './catalogOps'

function response(items: unknown[], nextCursor: string | null = null): Response {
  return new Response(JSON.stringify({ items, next_cursor: nextCursor, has_more: nextCursor !== null }), {
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(async () => {
  setActivePinia(createPinia())
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8000')
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  const auth = useAuthStore()
  await auth.loadMerchants()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
    session_id: 's'.repeat(43), role: 'MERCHANT', expires_at: '2026-09-30T00:00:00Z',
    merchant_display_name: 'Borough商家100',
  }), { headers: { 'content-type': 'application/json' } })))
  await auth.openSession(auth.merchants[0]!)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

it('商品与券有下一页时保留游标并可继续加载，避免只显示前 20 条', async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url.includes('/products/content')) {
      return Promise.resolve(response([], url.includes('cursor=') ? null : 'next-products'))
    }
    return Promise.resolve(response([], url.includes('cursor=') ? null : 'next-coupons'))
  })
  vi.stubGlobal('fetch', fetchMock)
  const store = useCatalogOpsStore()

  await store.load()
  expect(store.hasMoreProducts).toBe(true)
  expect(store.hasMoreCoupons).toBe(true)
  await store.loadMoreProducts()
  await store.loadMoreCoupons()
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes('cursor=next-products'))).toBe(true)
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes('cursor=next-coupons'))).toBe(true)
  expect(store.hasMoreProducts).toBe(false)
  expect(store.hasMoreCoupons).toBe(false)
})
