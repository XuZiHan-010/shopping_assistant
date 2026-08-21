import type { components } from '@/api/generated'
import type { DailyReport } from '@/types/report'

import { toDailyReport } from './adapters/report'
import { resolveTransport } from './transport'

export async function getDailyReport(signal: AbortSignal): Promise<DailyReport> {
  const transport = await resolveTransport()
  const response = await transport(
    { path: '/api/reports/daily', method: 'GET', auth: 'merchant' },
    signal,
  )
  return toDailyReport((await response.json()) as components['schemas']['DailyReportResponse'])
}
