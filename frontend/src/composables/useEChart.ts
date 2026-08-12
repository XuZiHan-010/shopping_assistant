import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'

import type { ChartOption } from '@/utils/chart'

echarts.use([
  LineChart,
  BarChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CanvasRenderer,
])

export function useEChart(
  container: Ref<HTMLElement | null>,
  option: Ref<ChartOption | undefined>,
  enabled: Ref<boolean>,
): void {
  let instance: echarts.ECharts | undefined
  let observer: ResizeObserver | undefined

  function dispose(): void {
    observer?.disconnect()
    observer = undefined
    instance?.dispose()
    instance = undefined
  }

  function render(): void {
    const element = container.value
    const chartOption = option.value
    if (!enabled.value || !element || element.clientWidth === 0 || !chartOption) {
      dispose()
      return
    }

    if (!instance) {
      instance = echarts.init(element)
      observer = new ResizeObserver(() => {
        window.requestAnimationFrame(() => instance?.resize())
      })
      observer.observe(element)
    }
    instance.setOption(chartOption as unknown as echarts.EChartsCoreOption, { notMerge: true })
  }

  onMounted(render)
  watch([option, enabled], render)
  onBeforeUnmount(dispose)
}
