/**
 * 首页趋势图（W Task 8）：ECharts 经 `useEChart` 渲染，数据点只来自 overview 响应，
 * 容器尺寸变化时重绘。
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { i18n } from '@/i18n'
import type { OverviewHeadline } from '@/types/merchantInsights'

import HomeTrendChart from './HomeTrendChart.vue'

const echartsMock = vi.hoisted(() => {
  const chartInstance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
  return { chartInstance, init: vi.fn(() => chartInstance) }
})

vi.mock('echarts/core', () => ({ init: echartsMock.init, use: vi.fn() }))

let resizeCallback: (() => void) | undefined

class ResizeObserverStub {
  constructor(callback: () => void) {
    resizeCallback = callback
  }
  observe = vi.fn()
  disconnect = vi.fn()
}

const headline: OverviewHeadline = {
  metricCode: 'net_gmv',
  currentCents: 1234500,
  baselineCents: 1300000,
  changeRatioBp: -504,
  currentSeries: [
    { date: '2026-09-21', valueCents: 400000 },
    { date: '2026-09-22', valueCents: 434500 },
    { date: '2026-09-23', valueCents: 400000 },
  ],
  baselineSeries: [
    { date: '2026-09-14', valueCents: 450000 },
    { date: '2026-09-15', valueCents: 450000 },
    { date: '2026-09-16', valueCents: 400000 },
  ],
}

function mountChart(value: OverviewHeadline = headline) {
  setActivePinia(createPinia())
  return mount(HomeTrendChart, {
    props: { headline: value, currentLabel: '本周', baselineLabel: '上周同日' },
    global: { plugins: [i18n] },
  })
}

type SeriesOption = { name: string; data: number[] }

function lastOption(): { series: SeriesOption[]; xAxis: { data: string[] } } {
  const calls = echartsMock.chartInstance.setOption.mock.calls
  return calls[calls.length - 1]![0] as { series: SeriesOption[]; xAxis: { data: string[] } }
}

beforeEach(() => {
  echartsMock.init.mockClear()
  echartsMock.chartInstance.setOption.mockClear()
  echartsMock.chartInstance.resize.mockClear()
  resizeCallback = undefined
  vi.stubGlobal('ResizeObserver', ResizeObserverStub)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 1
  })
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 480 })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('HomeTrendChart', () => {
  it('本期与基期两条折线的数据点逐一取自响应序列（分 → 元，只换单位）', async () => {
    mountChart()
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    const option = lastOption()
    expect(option.series).toHaveLength(2)
    expect(option.series[0]!.name).toBe('本周')
    expect(option.series[0]!.data).toEqual([4000, 4345, 4000])
    expect(option.series[1]!.name).toBe('上周同日')
    expect(option.series[1]!.data).toEqual([4500, 4500, 4000])
    expect(option.xAxis.data).toHaveLength(3)
  })

  it('基期无可比数据（空序列）时只画本期一条线', async () => {
    mountChart({ ...headline, baselineCents: null, changeRatioBp: null, baselineSeries: [] })
    await nextTick()

    expect(lastOption().series).toHaveLength(1)
  })

  it('容器尺寸变化时重绘', async () => {
    mountChart()
    await nextTick()
    expect(resizeCallback).toBeDefined()

    resizeCallback!()

    expect(echartsMock.chartInstance.resize).toHaveBeenCalledTimes(1)
  })

  it('画布旁附带可读的数据表（屏幕阅读器），数值同样来自响应', async () => {
    const wrapper = mountChart()
    await nextTick()
    const cells = wrapper.findAll('[data-test=trend-table] tbody tr')
    expect(cells).toHaveLength(3)
    expect(cells[1]!.text()).toContain('4,345.00')
  })
})
