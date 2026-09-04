import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { setLocaleProvider } from '@/api/credentials'
import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'

import { MERCHANT_STORAGE_KEY, useAuthStore } from './auth'
import { useLocaleStore } from './locale'

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
})
