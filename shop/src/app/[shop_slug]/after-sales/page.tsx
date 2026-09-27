import { AfterSalesClient } from './AfterSalesClient'
import { headers } from 'next/headers'

export default async function AfterSalesPage({
  searchParams,
}: {
  searchParams: Promise<{ order?: string }>
}) {
  const { order } = await searchParams
  const language = (await headers()).get('accept-language') ?? ''
  const locale = language.toLowerCase().startsWith('en') ? 'en-US' : 'zh-CN'
  return <AfterSalesClient orderId={order} locale={locale} />
}
