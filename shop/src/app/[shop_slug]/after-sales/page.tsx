import { AfterSalesClient } from './AfterSalesClient'
import { serverLocale } from '@/i18n/serverLocale'

export default async function AfterSalesPage({
  searchParams,
}: {
  searchParams: Promise<{ order?: string; case?: string }>
}) {
  const { order, case: caseId } = await searchParams
  const locale = await serverLocale()
  return <AfterSalesClient orderId={order} caseId={caseId} locale={locale} />
}
