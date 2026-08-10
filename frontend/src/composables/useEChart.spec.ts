import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChartOption } from '@/utils/chart'

const echartsMock = vi.hoisted(() => {
  const chartInstance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
  return { chartInstance, init: vi.fn(() => chartInstance) }
})

vi.mock('echarts/core', () => ({ init: echartsMock.init, use: vi.fn() }))

import { useEChart } from './useEChart'

class ResizeObserverStub {
  disconnect = vi.fn()
  observe = vi.fn()
}

const option: ChartOption = {
  animation: false,
  tooltip: {},
  series: [{ type: 'line', data: [1] }],
}

describe('useEChart', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
    echartsMock.chartInstance.setOption.mockClear()
    echartsMock.chartInstance.dispose.mockClear()
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 320 })
  })

  it('用 notMerge 更新图表，并在卸载时释放实例', async () => {
    const Harness = defineComponent({
      setup() {
        const element = ref<HTMLElement | null>(null)
        const chartOption = ref<ChartOption | undefined>(option)
        useEChart(element, chartOption, ref(true))
        return () => h('div', { ref: element })
      },
    })

    const wrapper = mount(Harness)
    await Promise.resolve()

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    expect(echartsMock.chartInstance.setOption).toHaveBeenCalledWith(option, { notMerge: true })

    wrapper.unmount()
    expect(echartsMock.chartInstance.dispose).toHaveBeenCalledTimes(1)
  })
})
