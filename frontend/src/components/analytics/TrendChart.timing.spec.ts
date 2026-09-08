import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const echartsMock = vi.hoisted(() => {
  const chartInstance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
  return { chartInstance, init: vi.fn(() => chartInstance) }
})

vi.mock('echarts/core', () => ({ init: echartsMock.init, use: vi.fn() }))

import type { ChatBiDailyPoint } from '@/types/analytics'

import TrendChart from './TrendChart.vue'

class ResizeObserverStub {
  disconnect = vi.fn()
  observe = vi.fn()
}

const point: ChatBiDailyPoint = {
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
}

describe('TrendChart 与真实 useEChart 的挂载时序', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.chartInstance.setOption.mockClear()
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 320 })
  })

  it('daily 迟到时容器与 option 同批出现，仍会初始化图表', async () => {
    const wrapper = mount(TrendChart, { props: { daily: [] as ChatBiDailyPoint[] } })

    expect(echartsMock.init).not.toHaveBeenCalled()

    await wrapper.setProps({ daily: [point] })
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    expect(echartsMock.chartInstance.setOption).toHaveBeenCalledTimes(1)
  })
})
