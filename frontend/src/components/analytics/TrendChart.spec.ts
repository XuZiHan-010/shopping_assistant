import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

let capturedOption: { value?: Record<string, unknown> } | undefined

vi.mock('@/composables/useEChart', () => ({
  useEChart: (_container: unknown, option: { value?: Record<string, unknown> }) => {
    capturedOption = option
  },
}))

import TrendChart from './TrendChart.vue'

describe('TrendChart', () => {
  it('将空比率保留为 null，供 ECharts 在趋势线上断开', () => {
    mount(TrendChart, {
      props: {
        daily: [
          {
            statDate: '2026-08-20',
            answerTotal: 8,
            metrics: {
              adoptionRate: 0.4,
              userAccuracyRate: null,
              systemAccuracyRate: 0.8,
              avgThinkingMs: 2100,
              hitRate: 0.9,
              failureRate: 0,
            },
          },
          {
            statDate: '2026-08-21',
            answerTotal: 12,
            metrics: {
              adoptionRate: null,
              userAccuracyRate: null,
              systemAccuracyRate: 0.75,
              avgThinkingMs: 1800,
              hitRate: null,
              failureRate: 0.1,
            },
          },
        ],
      },
    })

    const series = capturedOption?.value?.series as Array<Record<string, unknown>>
    expect(series[0]?.data).toEqual([40, null])
    expect(series[1]?.data).toEqual([90, null])
    expect(series[2]?.data).toEqual([8, 12])
  })
})
