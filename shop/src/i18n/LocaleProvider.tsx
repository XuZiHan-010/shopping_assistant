'use client'
import { createContext, useContext, useState, useLayoutEffect, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { setRequestLocale } from '../api/client'
import { LOCALE_COOKIE, type Locale } from './locale'
import { messages, type MessageKey } from './messages'
export function translate(locale: Locale, key: MessageKey, vars?: Record<string, string | number>): string {
  return messages[locale][key].replace(/\{(\w+)\}/g, (match, name: string) => String(vars?.[name] ?? match))
}
interface LocaleContextValue { locale: Locale; t: (key: MessageKey, vars?: Record<string, string | number>) => string; setLocale: (next: Locale) => void }
const LocaleContext = createContext<LocaleContextValue>({ locale: 'zh-CN', t: (key, vars) => translate('zh-CN', key, vars), setLocale: () => undefined })
export function LocaleProvider({ children, initialLocale = 'zh-CN' }: { children: ReactNode; initialLocale?: Locale }) {
  const [locale, updateLocale] = useState(initialLocale)
  const router = useRouter()
  useLayoutEffect(() => { setRequestLocale(locale); document.documentElement.lang = locale }, [locale])
  function setLocale(next: Locale) {
    setRequestLocale(next)
    document.cookie = `${LOCALE_COOKIE}=${next}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`
    updateLocale(next)
    router.refresh()
  }
  return <LocaleContext.Provider value={{ locale, t: (key, vars) => translate(locale, key, vars), setLocale }}>{children}</LocaleContext.Provider>
}
export function useLocale() { return useContext(LocaleContext) }
