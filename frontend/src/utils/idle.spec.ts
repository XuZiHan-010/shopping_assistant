import { afterEach, describe, expect, it, vi } from 'vitest'

import { whenIdle } from './idle'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('whenIdle（首屏之后再做的事）', () => {
  it('有 requestIdleCallback 时交给浏览器空闲回调，并带超时兜底', () => {
    const requestIdleCallback = vi.fn(() => 7)
    const cancelIdleCallback = vi.fn()
    vi.stubGlobal('requestIdleCallback', requestIdleCallback)
    vi.stubGlobal('cancelIdleCallback', cancelIdleCallback)
    const callback = vi.fn()

    const cancel = whenIdle(callback)

    expect(requestIdleCallback).toHaveBeenCalledWith(expect.any(Function), { timeout: 2000 })
    expect(callback).not.toHaveBeenCalled()
    cancel()
    expect(cancelIdleCallback).toHaveBeenCalledWith(7)
  })

  it('没有 requestIdleCallback（如 Safari）时退到下一轮宏任务', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestIdleCallback', undefined)
    const callback = vi.fn()

    whenIdle(callback)
    expect(callback).not.toHaveBeenCalled()
    vi.runAllTimers()

    expect(callback).toHaveBeenCalledTimes(1)
  })

  it('取消后不再执行', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestIdleCallback', undefined)
    const callback = vi.fn()

    const cancel = whenIdle(callback)
    cancel()
    vi.runAllTimers()

    expect(callback).not.toHaveBeenCalled()
  })
})
