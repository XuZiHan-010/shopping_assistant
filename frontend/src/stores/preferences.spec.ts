import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SIZE_STORAGE_KEY, THEME_STORAGE_KEY, usePreferencesStore } from './preferences'

const root = document.documentElement

function breakLocalStorage(): void {
  // 隐私模式 / 禁用站点数据时，连访问 `window.localStorage` 本身都可能抛错。
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
    throw new DOMException('denied', 'SecurityError')
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  delete root.dataset.theme
  delete root.dataset.size
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('偏好设置 store', () => {
  it('没有持久化值时回落到「跟随系统 + 标准字号」并写到 <html>', () => {
    const prefs = usePreferencesStore()
    prefs.restore()

    expect(prefs.theme).toBe('system')
    expect(prefs.size).toBe('md')
    expect(root.dataset.theme).toBe('system')
    expect(root.dataset.size).toBe('md')
  })

  it.each(['system', 'light', 'dark'] as const)('主题 %s 写入 data-theme 并持久化', (theme) => {
    const prefs = usePreferencesStore()
    prefs.setTheme(theme)

    expect(root.dataset.theme).toBe(theme)
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(theme)
  })

  it.each(['sm', 'md', 'lg'] as const)('字号 %s 写入 data-size 并持久化', (size) => {
    const prefs = usePreferencesStore()
    prefs.setSize(size)

    expect(root.dataset.size).toBe(size)
    expect(localStorage.getItem(SIZE_STORAGE_KEY)).toBe(size)
  })

  it('restore 读回上次的选择', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    localStorage.setItem(SIZE_STORAGE_KEY, 'lg')

    const prefs = usePreferencesStore()
    prefs.restore()

    expect(root.dataset.theme).toBe('dark')
    expect(root.dataset.size).toBe('lg')
  })

  it('持久化值不合法时忽略它', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'neon')
    localStorage.setItem(SIZE_STORAGE_KEY, 'xxl')

    const prefs = usePreferencesStore()
    prefs.restore()

    expect(prefs.theme).toBe('system')
    expect(prefs.size).toBe('md')
  })

  it('localStorage 抛错时读写都不抛，界面仍按内存里的选择生效', () => {
    breakLocalStorage()
    const prefs = usePreferencesStore()

    expect(() => prefs.restore()).not.toThrow()
    expect(root.dataset.theme).toBe('system')

    expect(() => prefs.setTheme('dark')).not.toThrow()
    expect(() => prefs.setSize('sm')).not.toThrow()
    expect(root.dataset.theme).toBe('dark')
    expect(root.dataset.size).toBe('sm')
  })
})
