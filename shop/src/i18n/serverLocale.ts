import { cookies, headers } from 'next/headers'
import { LOCALE_COOKIE, resolveLocale, type Locale } from './locale'
export async function serverLocale(): Promise<Locale> {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()])
  return resolveLocale(cookieStore.get(LOCALE_COOKIE)?.value, headerStore.get('accept-language'))
}
