import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 纯前端界面偏好：主题与界面字号（W Task 5，设计说明 §3.2「偏好设置」）。
 * 语言不在这里，仍由 `stores/locale.ts` 管理。
 *
 * 取值写到 `<html data-theme>` / `<html data-size>`，由 `assets/tokens.css`
 * 与 `assets/merchant-shell.css` 的选择器生效；`system` 交给
 * `prefers-color-scheme` 判定，本 store 不监听系统主题。
 */
export type ThemePreference = 'system' | 'light' | 'dark'
export type SizePreference = 'sm' | 'md' | 'lg'

export const THEME_OPTIONS: readonly ThemePreference[] = ['system', 'light', 'dark']
export const SIZE_OPTIONS: readonly SizePreference[] = ['sm', 'md', 'lg']

export const THEME_STORAGE_KEY = 'borough.theme'
export const SIZE_STORAGE_KEY = 'borough.size'

const DEFAULT_THEME: ThemePreference = 'system'
const DEFAULT_SIZE: SizePreference = 'md'

/**
 * localStorage 在隐私模式、禁用站点数据时可能连访问本身都抛错（不只是返回
 * `null`）。读写都包 try/catch：偏好只是便利，读不到就用默认值，写不进去就
 * 只在本次会话生效，页面渲染绝不能因此失败。
 */
function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const stored = window.localStorage.getItem(key)
    return (allowed as readonly string[]).includes(stored ?? '') ? (stored as T) : fallback
  } catch {
    return fallback
  }
}

function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // 忽略：本次会话照常按新选择渲染，只是刷新后回到默认值。
  }
}

export const usePreferencesStore = defineStore('preferences', () => {
  const theme = ref<ThemePreference>(DEFAULT_THEME)
  const size = ref<SizePreference>(DEFAULT_SIZE)

  function applyTheme(next: ThemePreference): void {
    theme.value = next
    document.documentElement.dataset.theme = next
  }

  function applySize(next: SizePreference): void {
    size.value = next
    document.documentElement.dataset.size = next
  }

  function setTheme(next: ThemePreference): void {
    applyTheme(next)
    writeStored(THEME_STORAGE_KEY, next)
  }

  function setSize(next: SizePreference): void {
    applySize(next)
    writeStored(SIZE_STORAGE_KEY, next)
  }

  /** 应用启动时在挂载前同步调用一次，首帧就是恢复后的主题与字号。 */
  function restore(): void {
    applyTheme(readStored(THEME_STORAGE_KEY, THEME_OPTIONS, DEFAULT_THEME))
    applySize(readStored(SIZE_STORAGE_KEY, SIZE_OPTIONS, DEFAULT_SIZE))
  }

  return { theme, size, setTheme, setSize, restore }
})
