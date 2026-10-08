import { readFileSync } from 'node:fs'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'

import { fetchMerchantMetricsOverview } from './merchantInsights'

const BASE_URL = 'http://127.0.0.1:8000'
const SESSION = 's'.repeat(43)

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function errorResponse(code: string, status: number): Response {
  return jsonResponse(
    { code, message: 'boom', request_id: 'req-1', details: [], retryable: false },
    status,
  )
}

function overviewPayload(overrides: Record<string, unknown> = {}) {
  return {
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    thinking_steps: [],
    quality_status: 'NOT_RUN',
    quality_attempts: 0,
    quality_notes: [],
    degraded: false,
    degraded_reason: null,
    business_timezone: 'Asia/Shanghai',
    data_as_of: '2026-09-28T00:00:00Z',
    source: 'REALTIME',
    definition_version: 'v1',
    current_period: { start: '2026-09-22', end: '2026-09-28', label: '本周' },
    baseline_period: { start: '2026-09-15', end: '2026-09-21', label: '上周' },
    headline: {
      metric_code: 'net_gmv',
      current_cents: 120000,
      baseline_cents: 100000,
      change_ratio_bp: 2000,
      current_series: [{ date: '2026-09-22', value_cents: 120000 }],
      baseline_series: [{ date: '2026-09-15', value_cents: 100000 }],
    },
    attribution: {
      dimension: 'category',
      mode: 'SHARE',
      segments: [
        {
          name: '女装',
          current_cents: 80000,
          baseline_cents: 60000,
          contribution_cents: 20000,
          share_bp: 5000,
        },
      ],
      remaining_count: 0,
      remaining_contribution_cents: 0,
      stopped_reason: null,
    },
    secondary: [
      { metric_code: 'order_count', unit: 'COUNT', current_value: 42, baseline_value: 30 },
      { metric_code: 'refund_amount', unit: 'CENTS', current_value: 500, baseline_value: 0 },
      { metric_code: 'return_rate', unit: 'RATIO_BP', current_value: 100, baseline_value: null },
    ],
    ...overrides,
  }
}

describe('merchantInsights adapter', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('拉取首页经营主指标并转成领域类型，带上会话头', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(overviewPayload()))
    vi.stubGlobal('fetch', fetchMock)

    const overview = await fetchMerchantMetricsOverview(SESSION)

    expect(overview.headline).toEqual({
      metricCode: 'net_gmv',
      currentCents: 120000,
      baselineCents: 100000,
      changeRatioBp: 2000,
      currentSeries: [{ date: '2026-09-22', valueCents: 120000 }],
      baselineSeries: [{ date: '2026-09-15', valueCents: 100000 }],
    })
    expect(overview.attribution.segments[0]).toEqual({
      name: '女装',
      currentCents: 80000,
      baselineCents: 60000,
      contributionCents: 20000,
      shareBp: 5000,
    })
    expect(overview.secondary).toEqual([
      { metricCode: 'order_count', unit: 'COUNT', currentValue: 42, baselineValue: 30 },
      { metricCode: 'refund_amount', unit: 'CENTS', currentValue: 500, baselineValue: 0 },
      { metricCode: 'return_rate', unit: 'RATIO_BP', currentValue: 100, baselineValue: null },
    ])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/metrics/overview`)
    expect((init.headers as Record<string, string>)['X-Session-Id']).toBe(SESSION)
    // 周期说明、停止原因与降级原因由后端按展示语言渲染（§8.6，R1），请求须带语言头（W Task 8）。
    expect((init.headers as Record<string, string>)['Accept-Language']).toMatch(/^(zh-CN|en-US)$/)
  })

  it('基期无可比数据时 baselineCents 与 changeRatioBp 原样保留为 null，不折成 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          overviewPayload({
            headline: {
              metric_code: 'net_gmv',
              current_cents: 120000,
              baseline_cents: null,
              change_ratio_bp: null,
              current_series: [{ date: '2026-09-22', value_cents: 120000 }],
              baseline_series: [],
            },
          }),
        ),
      ),
    )

    const overview = await fetchMerchantMetricsOverview(SESSION)

    expect(overview.headline.baselineCents).toBeNull()
    expect(overview.headline.changeRatioBp).toBeNull()
    expect(overview.headline.baselineSeries).toEqual([])
  })

  it('归因 STOPPED 时 segments 为空、stoppedReason 非空，原样映射', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          overviewPayload({
            attribution: {
              dimension: 'category',
              mode: 'STOPPED',
              segments: [],
              remaining_count: 0,
              remaining_contribution_cents: 0,
              stopped_reason: '归因查询超时',
            },
          }),
        ),
      ),
    )

    const overview = await fetchMerchantMetricsOverview(SESSION)

    expect(overview.attribution.mode).toBe('STOPPED')
    expect(overview.attribution.segments).toEqual([])
    expect(overview.attribution.stoppedReason).toBe('归因查询超时')
  })

  it('辅助指标 current_value 为 null 时原样保留，不折成 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          overviewPayload({
            secondary: [
              { metric_code: 'order_count', unit: 'COUNT', current_value: null, baseline_value: null },
              { metric_code: 'refund_amount', unit: 'CENTS', current_value: 0, baseline_value: 0 },
              { metric_code: 'return_rate', unit: 'RATIO_BP', current_value: null, baseline_value: null },
            ],
          }),
        ),
      ),
    )

    const overview = await fetchMerchantMetricsOverview(SESSION)

    expect(overview.secondary[0].currentValue).toBeNull()
    expect(overview.secondary[1].currentValue).toBe(0)
  })

  it('整体降级时如实映射 degraded / degradedReason / analysisSources', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          overviewPayload({
            degraded: true,
            degraded_reason: '归因查询超时，已降级为部分数据',
            analysis_sources: [{ source: 'DATABASE', degraded: true, degraded_reason: 'ATTRIBUTION_TIMEOUT' }],
          }),
        ),
      ),
    )

    const overview = await fetchMerchantMetricsOverview(SESSION)

    expect(overview.degraded).toBe(true)
    expect(overview.degradedReason).toBe('归因查询超时，已降级为部分数据')
    expect(overview.analysisSources).toEqual([
      { source: 'DATABASE', degraded: true, degradedReason: 'ATTRIBUTION_TIMEOUT' },
    ])
  })

  it('后端错误转成 AppError，调用方按 code 分支', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse('DATA_SOURCE_UNAVAILABLE', 503)))

    const error = await fetchMerchantMetricsOverview(SESSION).catch((cause) => cause)

    expect(error).toBeInstanceOf(AppError)
    expect((error as AppError).code).toBe('DATA_SOURCE_UNAVAILABLE')
  })

  it('Adapter 不对金额或万分比做浮点换算（换算交给 localizedFormat）', () => {
    const src = readFileSync('src/api/adapters/merchantInsights.ts', 'utf-8')
    expect(src).not.toMatch(/_cents\s*\/\s*100/)
    expect(src).not.toMatch(/_bp\s*\/\s*100/)
    expect(src).not.toMatch(/_bp\s*\/\s*10000/)
  })
})
