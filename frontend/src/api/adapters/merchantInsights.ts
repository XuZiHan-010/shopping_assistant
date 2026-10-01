/**
 * 首页经营主指标 Adapter（契约 §8.12.4，`GET /api/v2/merchant/metrics/overview`）。
 *
 * 周期由后端固定（本周 vs 上周同长度区间），不接受任何日期或商家参数；本端点没有
 * Reviewer，`qualityStatus` 恒为 `NOT_RUN`。金额保持整数分、万分比保持整数，
 * 换算成百分比或货币展示交给 `utils/localizedFormat.ts`，这里不做浮点转换。
 */
import { buildLocaleHeaders } from '@/api/credentials'
import type { components } from '@/api/generated'
import type {
  MerchantMetricsOverview,
  OverviewAttribution,
  OverviewHeadline,
  OverviewSecondaryMetric,
} from '@/types/merchantInsights'

import { merchantRequest } from './v2Http'

type RawOverview = components['schemas']['MerchantMetricsOverviewResponse']
type RawHeadline = components['schemas']['OverviewHeadline']
type RawAttribution = components['schemas']['OverviewAttribution']
type RawSecondary = components['schemas']['OverviewSecondaryMetric']

function toHeadline(raw: RawHeadline): OverviewHeadline {
  return {
    metricCode: raw.metric_code,
    currentCents: raw.current_cents,
    baselineCents: raw.baseline_cents,
    changeRatioBp: raw.change_ratio_bp,
    currentSeries: raw.current_series.map((point) => ({
      date: point.date,
      valueCents: point.value_cents,
    })),
    baselineSeries: raw.baseline_series.map((point) => ({
      date: point.date,
      valueCents: point.value_cents,
    })),
  }
}

function toAttribution(raw: RawAttribution): OverviewAttribution {
  return {
    dimension: raw.dimension,
    mode: raw.mode,
    segments: raw.segments.map((segment) => ({
      name: segment.name,
      currentCents: segment.current_cents,
      baselineCents: segment.baseline_cents,
      contributionCents: segment.contribution_cents,
      shareBp: segment.share_bp,
    })),
    remainingCount: raw.remaining_count,
    remainingContributionCents: raw.remaining_contribution_cents,
    stoppedReason: raw.stopped_reason,
  }
}

function toSecondary(raw: RawSecondary): OverviewSecondaryMetric {
  return {
    metricCode: raw.metric_code,
    unit: raw.unit,
    currentValue: raw.current_value,
    baselineValue: raw.baseline_value,
  }
}

export async function fetchMerchantMetricsOverview(
  sessionId: string,
): Promise<MerchantMetricsOverview> {
  // 周期说明、停止原因与降级原因由后端按展示语言渲染（§8.6，R1）。
  const response = await merchantRequest('/api/v2/merchant/metrics/overview', sessionId, {
    headers: buildLocaleHeaders(),
  })
  const payload = (await response.json()) as RawOverview
  return {
    businessTimezone: payload.business_timezone,
    dataAsOf: payload.data_as_of,
    source: payload.source,
    definitionVersion: payload.definition_version,
    currentPeriod: {
      start: payload.current_period.start,
      end: payload.current_period.end,
      label: payload.current_period.label,
    },
    baselinePeriod: {
      start: payload.baseline_period.start,
      end: payload.baseline_period.end,
      label: payload.baseline_period.label,
    },
    headline: toHeadline(payload.headline),
    attribution: toAttribution(payload.attribution),
    secondary: payload.secondary.map(toSecondary),
    analysisSources: payload.analysis_sources.map((entry) => ({
      source: entry.source,
      degraded: entry.degraded,
      degradedReason: entry.degraded_reason,
    })),
    qualityStatus: payload.quality_status,
    qualityAttempts: payload.quality_attempts,
    qualityNotes: payload.quality_notes ?? [],
    degraded: payload.degraded,
    degradedReason: payload.degraded_reason,
  }
}
