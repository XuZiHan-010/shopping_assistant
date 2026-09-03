import { defineStore } from 'pinia'
import { ref } from 'vue'

import { DEFAULT_LOCALE, i18n, SUPPORTED_LOCALES, type SupportedLocale } from '@/i18n'

export const LOCALE_STORAGE_KEY = 'borough.locale'

function isSupportedLocale(value: string | null): value is SupportedLocale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value ?? '')
}

/**
 * localStorage 在隐私模式、禁用站点数据或配额耗尽时可能直接抛异常
 * （不只是返回 `null`）——读写都要接住，语言切换本身不能因此失败，
 * 顶多是下次刷新回退默认语言。
 */
function readStoredLocale(): SupportedLocale {
  try {
    const stored = localStorage.getItem(LOCALE_STORAGE_KEY)
    return isSupportedLocale(stored) ? stored : DEFAULT_LOCALE
  } catch {
    return DEFAULT_LOCALE
  }
}

function writeStoredLocale(locale: SupportedLocale): void {
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    // 忽略：本次会话仍然按已切换的语言渲染，只是刷新后回不到这个选择。
  }
}

function applyLocale(locale: SupportedLocale): void {
  i18n.global.locale.value = locale
  document.documentElement.lang = locale
  document.title = i18n.global.t('appMeta.title')
}

export const useLocaleStore = defineStore('locale', () => {
  const locale = ref<SupportedLocale>(DEFAULT_LOCALE)

  function setLocale(next: SupportedLocale): void {
    locale.value = next
    applyLocale(next)
    writeStoredLocale(next)
  }

  /** 应用启动时调用一次：读取上次持久化的语言并让 Vue I18n/页面元数据同步。 */
  function restore(): void {
    setLocale(readStoredLocale())
  }

  function toggle(): void {
    setLocale(locale.value === 'zh-CN' ? 'en-US' : 'zh-CN')
  }

  return { locale, setLocale, restore, toggle }
})
