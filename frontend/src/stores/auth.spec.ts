import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setLocaleProvider } from '@/api/credentials'
import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'

import { MERCHANT_STORAGE_KEY, useAuthStore } from './auth'
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
