import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setLocaleProvider } from '@/api/credentials'
import { AppError } from '@/api/errors'
import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'

import { MERCHANT_STORAGE_KEY, registerSessionScopedReset, useAuthStore } from './auth'
import { useLocaleStore } from './locale'

/** 手动控制 settle 时机的 Promise，用来构造"谁先谁后返回"的确定性竞态。 */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function merchantsResponse(displayName: string): Response {
  return Response.json({
    merchants: [
      { merchant_id: 'merchant-100', display_name: displayName, token: 'demo-token-100' },
      { merchant_id: 'merchant-101', display_name: 'Borough商家101', token: 'demo-token-101' },
    ],
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  sessionStorage.clear()
})

afterEach(() => {
  setLocaleProvider(undefined)
})

describe('useAuthStore', () => {
  it('加载商家列表并默认选中第一个', async () => {
    const store = useAuthStore()

    await store.loadMerchants()

    expect(store.merchants.length).toBeGreaterThanOrEqual(2)
    expect(store.selected?.displayName).toBe('Borough商家100')
  })

  it('选中商家只把非敏感标识写入 sessionStorage，Token 不落盘', async () => {
    const store = useAuthStore()
    await store.loadMerchants()

    store.selectByDisplayName('Borough商家101')

    expect(sessionStorage.getItem(MERCHANT_STORAGE_KEY)).toBe('merchant-101')
    expect(JSON.stringify(sessionStorage)).not.toContain('demo-token')
    expect(JSON.stringify(localStorage)).not.toContain('demo-token')
  })

  it('restore 用持久化标识选回同一商家', async () => {
    sessionStorage.setItem(MERCHANT_STORAGE_KEY, 'merchant-102')
    const store = useAuthStore()

    await store.restore()

    expect(store.selected?.displayName).toBe('Borough商家102')
    expect(store.selected?.token).toBe('demo-token-102')
  })

  it('列表加载失败时不向调用方抛异常，而是留下可展示的提示', async () => {
    setChatTransport(async () => {
      throw new Error('网络中断')
    })
    const store = useAuthStore()

    await expect(store.restore()).resolves.toBeUndefined()

    expect(store.merchants).toEqual([])
    expect(store.restoreNotice).toContain('加载失败')
  })

  it('标识在列表中找不到时回退默认商家并给出提示', async () => {
    sessionStorage.setItem(MERCHANT_STORAGE_KEY, 'merchant-999')
    const store = useAuthStore()

    await store.restore()

    expect(store.selected?.merchantId).toBe('merchant-100')
    expect(store.restoreNotice).toContain('重新选择')
  })

  it('invalidate 清掉内存 Token 与 sessionStorage 标识，但保留商家列表与提示文案', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    store.selectByDisplayName('Borough商家101')
    expect(sessionStorage.getItem(MERCHANT_STORAGE_KEY)).toBe('merchant-101')

    store.invalidate()

    expect(store.selected?.token).toBeUndefined()
    // 身份失效不是「这个商家不存在了」——displayName/merchantId 还在，切换器
    // 重新打开时用户仍能看到「刚才选的是谁」，只是它已经没有可用凭证。
    expect(store.selected?.merchantId).toBe('merchant-101')
    expect(sessionStorage.getItem(MERCHANT_STORAGE_KEY)).toBeNull()
    expect(store.merchants.length).toBeGreaterThanOrEqual(2)
    expect(store.restoreNotice).toBe('演示身份已失效，请重新选择商家。')
  })
})

describe('v2 商家会话（n2-merchant-vue-v2-migration Task 2）', () => {
  const BASE_URL = 'http://127.0.0.1:8000'

  function sessionResponse(sessionId: string, displayName: string): Response {
    return Response.json({
      session_id: sessionId,
      role: 'MERCHANT',
      expires_at: '2026-09-24T00:00:00Z',
      merchant_display_name: displayName,
    })
  }

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('openSession 用 Bearer Token 换取会话 ID，只存内存不落任何持久化存储', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(sessionResponse('sid-a'.padEnd(43, '0'), 'Borough商家100')),
    )

    await store.openSession(store.merchants[0]!)

    expect(store.sessionId).toBe('sid-a'.padEnd(43, '0'))
    const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })
    expect(dump).not.toContain(store.sessionId)
  })

  it('切换商家：先注销旧会话、清空已注册的会话态 Store，再换取新会话，绝不复用旧 X-Session-Id', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    const resetSpy = vi.fn()
    const unregister = registerSessionScopedReset(resetSpy)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    fetchMock.mockResolvedValueOnce(sessionResponse('sid-a'.padEnd(43, '0'), 'Borough商家100'))
    await store.openSession(store.merchants[0]!)
    const firstSessionId = store.sessionId

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    fetchMock.mockResolvedValueOnce(sessionResponse('sid-b'.padEnd(43, '0'), 'Borough商家101'))
    await store.selectAndOpenSession(store.merchants[1]!)

    const [revokeUrl, revokeInit] = fetchMock.mock.calls[1]!
    expect(revokeUrl).toBe(`${BASE_URL}/api/v2/merchant/sessions/current`)
    expect(revokeInit.method).toBe('DELETE')
    expect((revokeInit.headers as Record<string, string>)['X-Session-Id']).toBe(firstSessionId)
    expect(resetSpy).toHaveBeenCalledTimes(1)
    expect(store.sessionId).not.toBe(firstSessionId)

    unregister()
  })

  it('注销旧会话失败不阻塞切换到新商家（旧会话终会按 TTL 过期）', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    fetchMock.mockResolvedValueOnce(sessionResponse('sid-a'.padEnd(43, '0'), 'Borough商家100'))
    await store.openSession(store.merchants[0]!)

    fetchMock.mockRejectedValueOnce(new TypeError('network down'))
    fetchMock.mockResolvedValueOnce(sessionResponse('sid-b'.padEnd(43, '0'), 'Borough商家101'))

    await expect(store.selectAndOpenSession(store.merchants[1]!)).resolves.toBeUndefined()
    expect(store.sessionId).toBe('sid-b'.padEnd(43, '0'))
  })

  it('callWithSessionRetry 遇到 SESSION_INVALID 时重新换取一次会话再重试一次，不直接向上抛错', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    // `mockImplementation` 而不是 `mockResolvedValue`：后者共享同一个 Response
    // 实例，第二次 openSession 再读 body 会撞上 happy-dom 的
    // "Body has already been used" ——每次调用都要一个新 Response；
    // 每次返回不同 session id，才能断言「重试时确实换到了新会话」而不是
    // 复用旧连接偶然读出同一个字符串。
    let sessionCallCount = 0
    const fetchMock = vi.fn().mockImplementation(async () => {
      sessionCallCount += 1
      return sessionResponse(`sid-${sessionCallCount}`.padEnd(43, '0'), 'Borough商家100')
    })
    vi.stubGlobal('fetch', fetchMock)
    await store.openSession(store.merchants[0]!)
    const staleSessionId = store.sessionId

    let attempts = 0
    const call = vi.fn(async (sid: string) => {
      attempts += 1
      if (attempts === 1) throw new AppError('SESSION_INVALID', '会话失效')
      return sid
    })

    const result = await store.callWithSessionRetry(call)

    expect(call).toHaveBeenCalledTimes(2)
    expect(result).not.toBe(staleSessionId)
    expect(result).toBe(store.sessionId)
  })

  it('callWithSessionRetry 连续两次都遇到 SESSION_INVALID 时把错误抛给调用方，不无限重试', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation(async () => sessionResponse('sid-a'.padEnd(43, '0'), 'Borough商家100')),
    )
    await store.openSession(store.merchants[0]!)

    const call = vi.fn(async () => {
      throw new AppError('SESSION_INVALID', '会话失效')
    })

    await expect(store.callWithSessionRetry(call)).rejects.toMatchObject({
      code: 'SESSION_INVALID',
    })
    expect(call).toHaveBeenCalledTimes(2)
  })

  it('当前商家没有可用凭证时 callWithSessionRetry 直接拒绝，不发出注定失败的请求', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    store.invalidate()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const call = vi.fn()

    await expect(store.callWithSessionRetry(call)).rejects.toMatchObject({
      code: 'AUTH_REQUIRED',
    })
    expect(call).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('没有会话时按需换取：直接打开 v2 页面也能用当前商家的 Token 建立会话', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sessionResponse('sid-lazy'.padEnd(43, '0'), 'Borough商家100'))
    vi.stubGlobal('fetch', fetchMock)

    const result = await store.callWithSessionRetry(async (sid) => sid)

    expect(result).toBe('sid-lazy'.padEnd(43, '0'))
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/sessions`)
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer demo-token-100')
  })

  it('刷新后（商家列表都没加载）按 sessionStorage 里的商家标识恢复再换取会话', async () => {
    sessionStorage.setItem(MERCHANT_STORAGE_KEY, 'merchant-101')
    const store = useAuthStore()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sessionResponse('sid-101'.padEnd(43, '0'), 'Borough商家101'))
    vi.stubGlobal('fetch', fetchMock)

    await store.callWithSessionRetry(async (sid) => sid)

    expect(store.selected?.merchantId).toBe('merchant-101')
    const init = fetchMock.mock.calls[0]![1]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer demo-token-101')
  })

  it('并发的会话态调用共用一次会话换取，不会一次页面加载建出两个会话', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    const fetchMock = vi
      .fn()
      .mockImplementation(async () => sessionResponse('sid-once'.padEnd(43, '0'), 'Borough商家100'))
    vi.stubGlobal('fetch', fetchMock)

    const [first, second] = await Promise.all([
      store.callWithSessionRetry(async (sid) => sid),
      store.callWithSessionRetry(async (sid) => sid),
    ])

    expect(first).toBe(second)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('通过商家切换器改选其他商家时，同步丢弃旧会话、清空会话态 Store，并注销旧会话', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sessionResponse('sid-a'.padEnd(43, '0'), 'Borough商家100'))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    await store.callWithSessionRetry(async (sid) => sid)
    const resetSpy = vi.fn()
    const unregister = registerSessionScopedReset(resetSpy)

    store.selectByDisplayName('Borough商家101')

    // 同步断言：切换器调用返回的那一刻，旧 X-Session-Id 已经不可用。
    expect(store.sessionId).toBeNull()
    expect(resetSpy).toHaveBeenCalledTimes(1)
    const [revokeUrl, revokeInit] = fetchMock.mock.calls[1]!
    expect(revokeUrl).toBe(`${BASE_URL}/api/v2/merchant/sessions/current`)
    expect(revokeInit.method).toBe('DELETE')
    expect((revokeInit.headers as Record<string, string>)['X-Session-Id']).toBe(
      'sid-a'.padEnd(43, '0'),
    )
    unregister()
  })

  it('改选的仍是同一个商家时不丢弃会话', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(sessionResponse('sid-a'.padEnd(43, '0'), 'Borough商家100')),
    )
    await store.callWithSessionRetry(async (sid) => sid)

    store.selectByDisplayName('Borough商家100')

    expect(store.sessionId).toBe('sid-a'.padEnd(43, '0'))
  })

  it('换取会话途中商家被切走：那枚会话属于旧商家，不装进来并尽力注销', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    const pendingSession = deferred<Response>()
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(pendingSession.promise)
      .mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    const inFlight = store.callWithSessionRetry(async (sid) => sid)
    store.selectByDisplayName('Borough商家101')
    pendingSession.resolve(sessionResponse('sid-stale'.padEnd(43, '0'), 'Borough商家100'))

    await expect(inFlight).rejects.toMatchObject({ code: 'AUTH_REQUIRED' })
    expect(store.sessionId).toBeNull()
    const revoked = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect((revoked![1].headers as Record<string, string>)['X-Session-Id']).toBe(
      'sid-stale'.padEnd(43, '0'),
    )
  })

  it('invalidate 同时丢弃 v2 会话', async () => {
    const store = useAuthStore()
    await store.loadMerchants()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(sessionResponse('sid-a'.padEnd(43, '0'), 'Borough商家100'))
        .mockResolvedValue(new Response(null, { status: 204 })),
    )
    await store.callWithSessionRetry(async (sid) => sid)

    store.invalidate()

    expect(store.sessionId).toBeNull()
  })
})

describe('语言切换：商家展示名重新本地化（Task 11 Step 6）', () => {
  it('切换语言后重新拉商家列表，展示名变化但 merchantId/token 不变', async () => {
    const store = useAuthStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    await store.loadMerchants()
    store.selectByDisplayName('Borough商家101')
    const merchantIdBefore = store.selected?.merchantId
    const tokenBefore = store.selected?.token

    localeStore.setLocale('en-US')
    await store.reloadForLocale()

    expect(store.selected?.displayName).toBe('Borough Merchant 101')
    expect(store.selected?.merchantId).toBe(merchantIdBefore)
    expect(store.selected?.token).toBe(tokenBefore)
  })

  it('身份已失效（token 为 undefined）时，语言切换刷新不会把 token 悄悄复活', async () => {
    const store = useAuthStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    await store.loadMerchants()
    store.selectByDisplayName('Borough商家101')
    store.invalidate()
    expect(store.selected?.token).toBeUndefined()

    localeStore.setLocale('en-US')
    await store.reloadForLocale()

    expect(store.selected?.displayName).toBe('Borough Merchant 101')
    expect(store.selected?.token).toBeUndefined()
  })

  it('尚未加载过商家列表时，reloadForLocale 是 no-op，不抢在 restore() 前面发请求', async () => {
    const store = useAuthStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)

    await store.reloadForLocale()

    expect(store.merchants).toEqual([])
    expect(store.selected).toBeUndefined()
  })

  it('刷新失败时静默保留当前列表和选中项，不抛出', async () => {
    const store = useAuthStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    await store.loadMerchants()
    store.selectByDisplayName('Borough商家100')
    const before = store.selected

    setChatTransport(async () => {
      throw new Error('网络中断')
    })
    localeStore.setLocale('en-US')

    await expect(store.reloadForLocale()).resolves.toBeUndefined()
    expect(store.selected).toEqual(before)
  })

  it('locale store 切换会自动触发 reloadForLocale（内部 watch），不需要调用方手动调用', async () => {
    const store = useAuthStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    await store.loadMerchants()
    store.selectByDisplayName('Borough商家102')

    localeStore.setLocale('en-US')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.selected?.displayName).toBe('Borough Merchant 102')
  })

  it('语言切换竞态：先发起的一次刷新响应晚到，不会覆盖后发生的那次已经写入的数据（真实乱序，epoch 防护）', async () => {
    const store = useAuthStore()
    const localeStore = useLocaleStore()
    setLocaleProvider(() => localeStore.locale)
    await store.loadMerchants()
    store.selectByDisplayName('Borough商家100')

    const first = deferred<Response>()
    const second = deferred<Response>()
    let callCount = 0
    setChatTransport(async () => {
      callCount += 1
      return callCount === 1 ? first.promise : second.promise
    })

    // 模拟"第一次刷新还没回来，语言又被切了一次"：手动调用一次
    // reloadForLocale（不经过 watch，代表任意一次仍在途的刷新，epoch 变成
    // 1），再切语言触发 watch 里的第二次 reloadForLocale（epoch 再 +1，
    // 发出新请求）。
    const staleReload = store.reloadForLocale()
    localeStore.setLocale('en-US')

    // 后发起的（较新 epoch）请求先回来。
    second.resolve(merchantsResponse('Second Response Name'))
    await vi.waitFor(() => expect(store.selected?.displayName).toBe('Second Response Name'))

    // 先发起的（较旧 epoch）请求后回来——必须被丢弃，不能覆盖上面已经写入的数据。
    first.resolve(merchantsResponse('Stale Response Name'))
    await staleReload
    // 给一次事件循环，确认"迟到的响应"确实被处理过（而不是还没跑到那一行）。
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.selected?.displayName).toBe('Second Response Name')
    expect(store.selected?.merchantId).toBe('merchant-100')
  })
})
