/**
 * 首页经营主指标（净成交额）的领域类型（契约 §8.12.4）。
 *
 * 金额保持整数分；万分比（`*Bp`）保持整数，换算成百分比展示交给
 * `utils/localizedFormat.ts` 的 `formatRatioBp`，这里不做浮点转换。
 */

export interface AnalysisSourceEntry {
  source: 'DATABASE' | 'KNOWLEDGE' | 'MEMORY' | 'FALLBACK' | 'NONE'
  degraded: boolean
  degradedReason: string | null
}

export type QualityStatus = 'PASSED' | 'DEGRADED' | 'FAILED' | 'NOT_RUN'

export interface OverviewPeriod {
  start: string
  end: string
  label: string
}

export interface OverviewMetricPoint {
  date: string
  valueCents: number
}

export interface OverviewHeadline {
  metricCode: 'net_gmv'
  currentCents: number
  /** `null` 表示基期无可比数据。 */
  baselineCents: number | null
  /** 万分比，`null` 表示基期为空或非正、不产生伪精确比例。 */
  changeRatioBp: number | null
  currentSeries: OverviewMetricPoint[]
  baselineSeries: OverviewMetricPoint[]
}

export type OverviewAttributionMode = 'SHARE' | 'ABSOLUTE_CONTRIBUTION' | 'STOPPED'

export interface OverviewAttributionSegment {
  name: string
  currentCents: number
  baselineCents: number
  contributionCents: number
  /** 仅 `mode = SHARE` 时非空。 */
  shareBp: number | null
}

export interface OverviewAttribution {
  dimension: 'category'
  mode: OverviewAttributionMode
  segments: OverviewAttributionSegment[]
  remainingCount: number
  remainingContributionCents: number
  /** 仅 `mode = STOPPED` 时非空，安全可理解，不含内部异常信息。 */
  stoppedReason: string | null
}

export type OverviewSecondaryMetricCode = 'order_count' | 'refund_amount' | 'return_rate'
export type OverviewSecondaryUnit = 'COUNT' | 'CENTS' | 'RATIO_BP'

export interface OverviewSecondaryMetric {
  metricCode: OverviewSecondaryMetricCode
  unit: OverviewSecondaryUnit
  /** `null` 表示无数据，不得展示成 0。 */
  currentValue: number | null
  baselineValue: number | null
}

export type MerchantMetricsOverviewSource = 'REALTIME' | 'DAILY_ROLLUP' | 'MIXED'

export interface MerchantMetricsOverview {
  businessTimezone: string
  dataAsOf: string
  source: MerchantMetricsOverviewSource
  definitionVersion: string
  currentPeriod: OverviewPeriod
  baselinePeriod: OverviewPeriod
  headline: OverviewHeadline
  attribution: OverviewAttribution
  secondary: OverviewSecondaryMetric[]
  analysisSources: AnalysisSourceEntry[]
  qualityStatus: QualityStatus
  qualityAttempts: number
  qualityNotes: string[]
  degraded: boolean
  degradedReason: string | null
}
