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
  // 容器是 v-if 控制的子节点；它本身出现或消失就是渲染时机，不能只靠 enabled 代替。
  // flush 必须是 post：option 与容器可能在同一次更新中出现，默认 pre 会早于 DOM 打补丁。
  watch([option, enabled, container], render, { flush: 'post' })
  onBeforeUnmount(dispose)
}
