import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getSession, resetSessionForTest } from '@/api/credentials'
import { apiErrorBody, json, stubBackend } from '@/test/fakeBackend'
import { bindDemoCustomer, openShopSession, switchDemoIdentity } from './sessionService'

const SESSION_ID = 'sess-secret-0123456789'

const guest = () => json(201, { session_id: SESSION_ID, role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' })
const bound = (cartAdjusted = false) =>
  json(200, { role: 'CUSTOMER', is_bound: true, expires_at: '2099-01-01T00:00:00Z', cart_adjusted: cartAdjusted })

beforeEach(() => {
  resetSessionForTest()
  window.history.replaceState(null, '', '/borough-100')
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe('顾客会话', () => {
  it('会话 ID 不进入 URL', async () => {
    stubBackend({ 'POST /api/v2/shop/sessions': guest })
    await openShopSession('borough-100')
    expect(getSession()?.sessionId).toBe(SESSION_ID)
    expect(window.location.href).not.toContain(SESSION_ID)
  })

  it('会话 ID 不落持久化存储（PRD C3 裁定）', async () => {
    stubBackend({ 'POST /api/v2/shop/sessions': guest, 'POST /api/v2/shop/sessions/demo-customer': () => bound() })
    await openShopSession('borough-100')
    await bindDemoCustomer()
    const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }) + document.cookie
    expect(dump).not.toContain(SESSION_ID)
  })

  it('同一店铺重复进入不重复创建会话', async () => {
    const backend = stubBackend({ 'POST /api/v2/shop/sessions': guest })
    await openShopSession('borough-100')
    await openShopSession('borough-100')
    expect(backend.called('POST /api/v2/shop/sessions')).toHaveLength(1)
  })

  it('并发进入同一店铺（如 React 严格模式重复挂载）只创建一次会话', async () => {
    const backend = stubBackend({ 'POST /api/v2/shop/sessions': guest })
    const [a, b] = await Promise.all([openShopSession('borough-100'), openShopSession('borough-100')])
    expect(a.sessionId).toBe(b.sessionId)
    expect(backend.called('POST /api/v2/shop/sessions')).toHaveLength(1)
  })

  it('跨店请求反序完成时，旧店铺响应不能覆盖当前店铺凭证', async () => {
    const releases = new Map<string, (response: Response) => void>()
    stubBackend({
      'POST /api/v2/shop/sessions': ({ body }) =>
        new Promise<Response>((resolve) => {
          releases.set((body as { shop_slug: string }).shop_slug, resolve)
        }),
    })

    const first = openShopSession('borough-100')
    const second = openShopSession('borough-200')
    releases.get('borough-200')?.(
      json(201, { session_id: 'sess-B', role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' }),
    )
    await second
    expect(getSession()).toMatchObject({ shopSlug: 'borough-200', sessionId: 'sess-B' })

    releases.get('borough-100')?.(
      json(201, { session_id: 'sess-A', role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' }),
    )
    await first
    expect(getSession()).toMatchObject({ shopSlug: 'borough-200', sessionId: 'sess-B' })
  })

  it('返回已有店铺会话后，另一店铺未完成的请求不能覆盖凭证', async () => {
    let releaseA: (response: Response) => void = () => {
      throw new Error('店铺 A 请求未发出')
    }
    stubBackend({
      'POST /api/v2/shop/sessions': ({ body }) =>
        (body as { shop_slug: string }).shop_slug === 'borough-100'
          ? new Promise<Response>((resolve) => { releaseA = resolve })
          : json(201, { session_id: 'sess-B', role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' }),
    })

    await openShopSession('borough-200')
    const first = openShopSession('borough-100')
    await openShopSession('borough-200')
    releaseA(json(201, { session_id: 'sess-A', role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' }))
    await first
    expect(getSession()).toMatchObject({ shopSlug: 'borough-200', sessionId: 'sess-B' })
  })

  it('请求体带 shop_slug，绑定请求只带 X-Session-Id 头', async () => {
    const backend = stubBackend({
      'POST /api/v2/shop/sessions': guest,
      'POST /api/v2/shop/sessions/demo-customer': () => bound(),
    })
    await openShopSession('borough-100')
    await bindDemoCustomer()
    expect(backend.calls[0]?.body).toEqual({ shop_slug: 'borough-100' })
    expect(backend.calls[1]?.headers['X-Session-Id']).toBe(SESSION_ID)
    expect(backend.calls[1]?.path).not.toContain(SESSION_ID)
  })

  it('绑定后会话标记为已绑定，并回传 cart_adjusted', async () => {
    stubBackend({ 'POST /api/v2/shop/sessions': guest, 'POST /api/v2/shop/sessions/demo-customer': () => bound(true) })
    await openShopSession('borough-100')
    const result = await bindDemoCustomer()
    expect(result.cartAdjusted).toBe(true)
    expect(getSession()?.isBound).toBe(true)
    expect(getSession()?.sessionId).toBe(SESSION_ID)
  })

  it('已绑定顾客换身份前先注销当前会话', async () => {
    let created = 0
    const backend = stubBackend({
      'POST /api/v2/shop/sessions': () =>
        json(201, { session_id: `sess-${++created}`, role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' }),
      'POST /api/v2/shop/sessions/demo-customer': () => bound(),
      'DELETE /api/v2/shop/sessions/current': () => json(204, null),
    })
    await openShopSession('borough-100')
    await bindDemoCustomer()
    await switchDemoIdentity('borough-100')

    const order = backend.calls.map((c) => `${c.method} ${c.path}`)
    expect(order).toEqual([
      'POST /api/v2/shop/sessions',
      'POST /api/v2/shop/sessions/demo-customer',
      'DELETE /api/v2/shop/sessions/current',
      'POST /api/v2/shop/sessions',
    ])
    expect(backend.calls[2]?.headers['X-Session-Id']).toBe('sess-1')
    expect(getSession()).toMatchObject({ sessionId: 'sess-2', isBound: false })
  })

  it('注销失败时仍清掉本地会话并新建访客会话', async () => {
    let created = 0
    stubBackend({
      'POST /api/v2/shop/sessions': () =>
        json(201, { session_id: `sess-${++created}`, role: 'CUSTOMER', expires_at: '2099-01-01T00:00:00Z' }),
      'DELETE /api/v2/shop/sessions/current': () => json(401, apiErrorBody('SESSION_INVALID')),
    })
    await openShopSession('borough-100')
    await switchDemoIdentity('borough-100')
    expect(getSession()?.sessionId).toBe('sess-2')
  })
})
