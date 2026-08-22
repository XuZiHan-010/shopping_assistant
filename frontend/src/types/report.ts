export interface DailyReportMetric {
  code: string
  displayName: string
  unit: string
  value: string | number
}

export interface DailyReport {
  answerId: string
  reportDate: string
  metrics: DailyReportMetric[]
  suggestions: string[]
  degraded: boolean
  degradedReason?: string
}
