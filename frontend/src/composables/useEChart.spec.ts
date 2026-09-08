import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
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

  it('容器随 option 一起出现时仍会初始化图表', async () => {
    // MetricChartPanel 把容器放在 `v-if="validation.renderable && chart"` 后面：
    // 首个带图表的回答到达时，option 和容器是同一次更新里出现的。上面那条用例
    // 的容器无条件渲染，走不到这条路径——首屏空图表正是从这里漏过去的。
    const chartOption = ref<ChartOption | undefined>(undefined)
    const enabled = ref(false)

    const Harness = defineComponent({
      setup() {
        const element = ref<HTMLElement | null>(null)
        useEChart(element, chartOption, enabled)
        return () => (enabled.value ? h('div', { ref: element }) : h('p', '暂无图表'))
      },
    })

    mount(Harness)
    expect(echartsMock.init).not.toHaveBeenCalled()

    chartOption.value = option
    enabled.value = true
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    expect(echartsMock.chartInstance.setOption).toHaveBeenCalledWith(option, { notMerge: true })
  })
  it('容器晚于 enabled 出现时补上初始化，而不是静默放弃', async () => {
    const chartOption = ref<ChartOption | undefined>(option)
    const enabled = ref(true)
    const containerReady = ref(false)

    const Harness = defineComponent({
      setup() {
        const element = ref<HTMLElement | null>(null)
        useEChart(element, chartOption, enabled)
        return () => (containerReady.value ? h('div', { ref: element }) : h('p', '容器还没到'))
      },
    })

    mount(Harness)
    await nextTick()
    expect(echartsMock.init).not.toHaveBeenCalled()

    containerReady.value = true
    await nextTick()

    expect(echartsMock.init).toHaveBeenCalledTimes(1)
    expect(echartsMock.chartInstance.setOption).toHaveBeenCalledWith(option, { notMerge: true })
  })
})
