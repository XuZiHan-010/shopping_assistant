import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'

import { MERCHANT_STORAGE_KEY, useAuthStore } from './auth'

beforeEach(() => {
  setActivePinia(createPinia())
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  sessionStorage.clear()
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
})
