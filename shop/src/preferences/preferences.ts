export type Theme = 'system' | 'light' | 'dark'
export type TextSize = 'sm' | 'md' | 'lg'
export interface Preferences { theme: Theme; size: TextSize }
export const PREFS_KEY = 'borough-shop-prefs'
export function loadPreferences(): Preferences {
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}')
    return { theme: ['system', 'light', 'dark'].includes(p?.theme) ? p.theme : 'system', size: ['sm', 'md', 'lg'].includes(p?.size) ? p.size : 'md' }
  } catch { return { theme: 'system', size: 'md' } }
}
export function applyPreferences(p: Preferences): void {
  document.documentElement.dataset.theme = p.theme
  document.documentElement.dataset.size = p.size
}
export function savePreferences(p: Preferences): void {
  applyPreferences(p)
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)) } catch { /* 隐私模式仍即时应用偏好 */ }
}
