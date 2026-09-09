import type { components } from '@/api/generated'
import type { DailyReport } from '@/types/report'

import { toDailyReport } from './adapters/report'
import { resolveTransport } from './transport'

/**
 * 展示语言不需要在这里显式处理：`resolveTransport()` 解析出的
 * `createFetchTransport()` 已经在装配请求头时统一带上 `Accept-Language`
 * （`transport.ts`，Task 11 Step 5），后端据此返回已经本地化好的
 * `display_name`/`suggestions` 等字段，本文件和下面的 Adapter 只需要原样
 * 转换 snake_case → camelCase，不做任何前端侧翻译。
 */

export async function getDailyReport(signal: AbortSignal): Promise<DailyReport> {
  const transport = await resolveTransport()
  const response = await transport(
    { path: '/api/reports/daily', method: 'GET', auth: 'merchant' },
    signal,
  )
  return toDailyReport((await response.json()) as components['schemas']['DailyReportResponse'])
}
