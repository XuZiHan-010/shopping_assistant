import { cookies } from 'next/headers'
import { LOCALE_COOKIE, resolveLocale, type Locale } from './locale'
export async function serverLocale(): Promise<Locale> {
  return resolveLocale((await cookies()).get(LOCALE_COOKIE)?.value)
}
