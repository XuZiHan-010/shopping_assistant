/**
 * 首页组件测试的共用装配（只供 `*.spec.ts` 引用，不进构建产物）。
 *
 * 刻意不导入 vitest：本目录在应用 tsconfig 的 include 范围内，这里只放纯函数，
 * `vi.stubGlobal` 等由各 spec 自己调用。
 */
import { createPinia, setActivePinia, type Pinia } from 'pinia'

import { useAuthStore } from '@/stores/auth'

import { errorResponse, jsonResponse } from './homePayloads'

export const TEST_BASE_URL = 'http://127.0.0.1:8000'
export const TEST_SESSION_ID = 'sid'.padEnd(43, '0')

/** 建 Pinia 并直接装上一枚可用会话，`ensureSession()` 不再发会话请求。 */
export function pinnedSessionPinia(displayName = 'Borough商家100'): Pinia {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.selected = { merchantId: 'merchant-100', displayName, token: 'demo-token' }
  auth.sessionId = TEST_SESSION_ID
  return pinia
}

export type RouteHandler = (url: URL, init?: RequestInit) => Response | Promise<Response>

/**
 * 按路径前缀分发的 fetch 替身。表里越靠前优先级越高；没有命中的请求返回 404，
 * 让“意外请求”在断言里显形，而不是被默认空载荷吞掉。
 */
export function routeFetch(routes: Array<[string, RouteHandler]>) {
  return async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const url = new URL(
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
    )
    for (const [prefix, handler] of routes) {
      if (url.pathname.startsWith(prefix)) return handler(url, init)
    }
    return errorResponse(404, 'RESOURCE_FORBIDDEN')
  }
}

export function json(payload: unknown): RouteHandler {
  return () => jsonResponse(payload)
}

export function failing(status = 503): RouteHandler {
  return () => errorResponse(status)
}

/** 立即执行的 `requestIdleCallback` 替身：测试里“空闲”即刻到来。 */
export function idleNow(callback: IdleRequestCallback): number {
  callback({ didTimeout: false, timeRemaining: () => 50 })
  return 1
}

/** 永不回调的 `requestIdleCallback` 替身：模拟首屏门禁里冻结的空闲回调。 */
export function idleNever(): number {
  return 1
}

/**
 * `IntersectionObserver` 替身：`observe()` 后记住回调，由测试调用 `reveal()`
 * 决定元素何时进入视口。
 */
export class ManualIntersectionObserver {
  static instances: ManualIntersectionObserver[] = []
  private readonly callback: IntersectionObserverCallback
  private readonly targets: Element[] = []

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    ManualIntersectionObserver.instances.push(this)
  }

  observe(target: Element): void {
    this.targets.push(target)
  }

  unobserve(): void {}

  disconnect(): void {
    this.targets.length = 0
  }

  takeRecords(): IntersectionObserverEntry[] {
    return []
  }

  static revealAll(): void {
    for (const observer of ManualIntersectionObserver.instances) {
      const entries = observer.targets.map(
        (target) => ({ isIntersecting: true, target }) as unknown as IntersectionObserverEntry,
      )
      if (entries.length > 0) {
        observer.callback(entries, observer as unknown as IntersectionObserver)
      }
    }
  }

  static reset(): void {
    ManualIntersectionObserver.instances = []
  }
}
