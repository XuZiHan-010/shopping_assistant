import type { components } from '@/api/generated'
import type { DailyReport } from '@/types/report'

type RawDailyReport = components['schemas']['DailyReportResponse']

export function toDailyReport(raw: RawDailyReport): DailyReport {
  return {
    answerId: raw.answer_id,
    reportDate: raw.report_date,
    metrics: (raw.metrics ?? []).map((metric) => ({
      code: metric.metric_code,
      displayName: metric.display_name,
      unit: metric.unit,
      value: metric.value,
    })),
    suggestions: raw.suggestions,
    degraded: raw.degraded,
    degradedReason: raw.degraded_reason ?? undefined,
  }
}
