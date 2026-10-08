import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

import { whenIdle } from '@/utils/idle'

/**
 * 「空闲之后、且进入视口」才变为 `true`（W Task 8 首页趋势图）。
 *
 * 首页趋势图经 `defineAsyncComponent` 懒加载 ECharts，挂载条件就是本函数的返回值：
 * 首屏关键路径上既不下载也不执行 ECharts（`scripts/check-first-paint.mjs` 正向检查
 * 首页图表宿主用的是它）。没有 `IntersectionObserver` 的环境按“可见”处理。
 * 一旦变为 `true` 就不再回落，图表不会因滚出视口而反复销毁重建。
 */
export function useIdleVisible(target: Ref<HTMLElement | null>): Ref<boolean> {
  const ready = ref(false)
  const idle = ref(false)
  const visible = ref(false)
  let cancelIdle: (() => void) | undefined
  let observer: IntersectionObserver | undefined

  function update(): void {
    if (idle.value && visible.value) {
      ready.value = true
      observer?.disconnect()
      observer = undefined
    }
  }

  function observe(element: HTMLElement | null): void {
    observer?.disconnect()
    observer = undefined
    if (!element || visible.value) return
    const Observer = globalThis.IntersectionObserver
    if (typeof Observer !== 'function') {
      visible.value = true
      update()
      return
    }
    observer = new Observer((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        visible.value = true
        update()
      }
    })
    observer.observe(element)
  }

  onMounted(() => {
    cancelIdle = whenIdle(() => {
      idle.value = true
      update()
    })
  })
  // 宿主容器可能晚于组件挂载才出现（数据到达后才渲染）：容器变化时重新观察。
  watch(target, observe, { flush: 'post', immediate: true })

  onBeforeUnmount(() => {
    cancelIdle?.()
    observer?.disconnect()
  })

  return ready
}
