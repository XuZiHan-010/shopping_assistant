/**
 * 把「首屏之后再做的事」推迟到浏览器空闲时（W Task 8 首页取数与趋势图挂载）。
 *
 * 首屏门禁（`e2e/first-paint.spec.ts`）冻结 `requestIdleCallback` 来观察首次可交互
 * 画面：经这里推迟的请求与图表不会出现在首屏请求序列里。`timeout` 保证主线程一直
 * 忙时也不会无限期推迟；没有 `requestIdleCallback` 的浏览器（Safari）退到下一轮宏任务。
 *
 * 返回取消函数，组件卸载时调用，避免卸载后才回调。
 */
export function whenIdle(callback: () => void, timeout = 2000): () => void {
  const requestIdle = globalThis.requestIdleCallback
  if (typeof requestIdle === 'function') {
    const handle = requestIdle(() => callback(), { timeout })
    return () => globalThis.cancelIdleCallback?.(handle)
  }
  const handle = globalThis.setTimeout(callback, 1)
  return () => globalThis.clearTimeout(handle)
}
