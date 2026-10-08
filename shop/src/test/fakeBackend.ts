import { vi } from 'vitest'

export interface RecordedCall {
  method: string
  path: string
  headers: Record<string, string>
  body: unknown
}

type Handler = (call: RecordedCall) => Response | Promise<Response>

export function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function sse(text: string): Response {
  return new Response(new TextEncoder().encode(text), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

export function apiErrorBody(code: string, message = code, details: unknown[] = []) {
  return { code, message, request_id: 'req-test', details, retryable: false }
}

/**
 * 在 fetch 边界替身后端：真实 client / adapter / 会话代码都会执行，
 * 只有网络被替换。路由键形如 `POST /api/v2/shop/sessions`。
 */
export function stubBackend(routes: Record<string, Handler>) {
  const calls: RecordedCall[] = []
  const fetchStub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input))
    const method = (init?.method ?? 'GET').toUpperCase()
    const call: RecordedCall = {
      method,
      path: url.pathname,
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    }
    calls.push(call)
    const handler = routes[`${method} ${url.pathname}`]
    if (!handler) throw new Error(`未登记的路由：${method} ${url.pathname}`)
    return handler(call)
  })
  vi.stubGlobal('fetch', fetchStub)
  return { calls, fetchStub, called: (key: string) => calls.filter((c) => `${c.method} ${c.path}` === key) }
}
