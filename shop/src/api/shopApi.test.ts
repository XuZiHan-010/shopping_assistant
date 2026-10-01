import { afterEach, expect, it, vi } from 'vitest'
import { listOrders, NoSessionError } from './shopApi'
import { setSession } from './credentials'

afterEach(() => { setSession(null); vi.unstubAllGlobals(); vi.unstubAllEnvs() })
it('订单列表从内存取会话并只请求首页', async () => {
  vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.test')
  setSession({ sessionId: 'session-a', shopSlug: 'borough-100', isBound: true, expiresAt: '2030-01-01' })
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 }))
  vi.stubGlobal('fetch', fetcher)
  expect(await listOrders()).toEqual([])
  expect(fetcher).toHaveBeenCalledWith('https://api.example.test/api/v2/shop/orders?limit=20', expect.objectContaining({ headers: expect.objectContaining({ 'X-Session-Id': 'session-a' }) }))
})
it('无会话时不发订单请求', async () => {
  setSession(null)
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  await expect(listOrders()).rejects.toBeInstanceOf(NoSessionError)
  expect(fetcher).not.toHaveBeenCalled()
})
