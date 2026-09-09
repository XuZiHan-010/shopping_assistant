import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { LOCALE_STORAGE_KEY, useLocaleStore } from './locale'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.documentElement.lang = ''
})

describe('useLocaleStore', () => {
  it('defaults to zh-CN when nothing is stored', () => {
    const store = useLocaleStore()

    store.restore()

    expect(store.locale).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
  })

  it('restores en-US and updates document language', () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, 'en-US')
    const store = useLocaleStore()
    store.restore()
    expect(store.locale).toBe('en-US')
    expect(document.documentElement.lang).toBe('en-US')
  })

  it('falls back to zh-CN when the stored value is not a supported locale', () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, 'fr-FR')
    const store = useLocaleStore()

    store.restore()

    expect(store.locale).toBe('zh-CN')
    expect(document.documentElement.lang).toBe('zh-CN')
  })

  it('setLocale persists the choice and updates document language + title', () => {
    const store = useLocaleStore()

    store.setLocale('en-US')

    expect(store.locale).toBe('en-US')
    expect(document.documentElement.lang).toBe('en-US')
    expect(document.title).toBe('Borough Merchant AI Assistant')
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en-US')

    store.setLocale('zh-CN')

    expect(document.documentElement.lang).toBe('zh-CN')
    expect(document.title).toBe('Borough 商家 AI 助手')
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN')
  })

  it('toggle switches between the two supported locales', () => {
    const store = useLocaleStore()
    store.restore()

    store.toggle()
    expect(store.locale).toBe('en-US')

    store.toggle()
    expect(store.locale).toBe('zh-CN')
  })

  it('does not throw when localStorage is unavailable', () => {
    const original = globalThis.localStorage
    // 模拟隐私模式/禁用存储：访问 localStorage 直接抛异常。
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('storage disabled')
      },
    })

    const store = useLocaleStore()
    expect(() => store.restore()).not.toThrow()
    expect(store.locale).toBe('zh-CN')

    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: original,
    })
  })
})
