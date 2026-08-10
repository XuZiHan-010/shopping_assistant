/**
 * 传输层。Mock 与真实实现的唯一分叉点。
 *
 * F2 只提供 Mock 分支；F3 在此补真实 fetch、鉴权头装配和错误码分支，
 * 上层（sse.ts、api/chat.ts、Store）一行都不用改。
 *
 * Mock 走动态 import 且由环境变量守卫，生产构建不包含 fixture 镜像。
 */
import type { components } from '@/api/generated'

import { resolveApiBaseUrl } from './client'
import { buildAuthHeaders } from './credentials'
import { AppError, toAppError } from './errors'

export interface TransportRequest {
  path: string
  method: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  accept?: string
  /**
   * 这次请求要携带哪种凭证，见 `credentials.ts` 的 `buildAuthHeaders`。
   * 省略时默认为 `'merchant'`——绝大多数接口都是商家接口，只有少数公开接口
   * （如演示商家列表）或未来的管理接口需要显式指定 `'none'` / `'admin'`。
   * 默认值由真实 transport（F3 后续任务）在读取该字段时应用。
   */
  auth?: 'merchant' | 'admin' | 'none'
}

export type ChatTransport = (req: TransportRequest, signal: AbortSignal) => Promise<Response>

let override: ChatTransport | undefined
let cached: ChatTransport | undefined

/** 测试注入用。传 undefined 恢复默认解析。 */
export function setChatTransport(transport: ChatTransport | undefined): void {
  override = transport
  cached = undefined
}

/**
 * 丢弃缓存的传输实例，下次 resolveTransport() 重新构造一个。
 *
 * F2 时期用于切换演示商家：Mock 的会话表挂在传输实例上，不重建的话上一个
 * 商家的历史会话会留在表里。F3 Task 7 起 Mock 自己按收到的 Authorization 头
 * 分租户（见 `mock/transport.ts` 的 `conversationsByTenant`），真实后端本就
 * 按 Token 过滤，两边都不再需要靠丢弃整个传输实例来做隔离——应用代码
 * （`src/views/**`、`src/components/**`）不应再调用这个函数。
 *
 * 仍然导出：测试需要在同一份 `override` 之外验证「重新解析传输」这条路径，
 * 保留给测试用。
 *
 * 不动 override：测试注入的传输由测试自己掌控，不该被业务代码清掉。
 */
export function resetTransportCache(): void {
  cached = undefined
}

export function isMockEnabled(): boolean {
  return import.meta.env.VITE_USE_MOCK === 'true'
}

type ErrorResponsePayload = components['schemas']['ErrorResponse']

/**
 * 后端 `ErrorResponse` 的运行时形状校验。`response.json()` 之后拿到的是
 * `unknown`——502 网关错误、静态资源 404 页面等都可能落进这个分支，body 未必
 * 是这份契约的 JSON，得先确认必填字段齐全再喂给 `AppError.fromErrorResponse`。
 */
function isErrorResponsePayload(value: unknown): value is ErrorResponsePayload {
  if (typeof value !== 'object' || value === null) return false
  const record = value as Record<string, unknown>
  return (
    typeof record.code === 'string' &&
    typeof record.message === 'string' &&
    typeof record.request_id === 'string' &&
    typeof record.retryable === 'boolean'
  )
}

/**
 * 把非 2xx 响应归一为 `AppError`。只在这里读 body——2xx 分支绝不能读，
 * 否则 SSE 的流就在这一层被提前消费掉了，上层（sse.ts）再也读不到任何字节。
 *
 * body 不是合法 JSON，或 JSON 不满足 `ErrorResponse` 的必填字段（例如反向代理
 * 直接吐出的 HTML 错误页）时，退回 `HTTP_ERROR` 并保留 HTTP 状态码，不假装
 * 认得这个 body。
 */
async function toHttpError(response: Response): Promise<AppError> {
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    payload = undefined
  }

  if (isErrorResponsePayload(payload)) {
    return AppError.fromErrorResponse(payload, response.status)
  }

  return new AppError('HTTP_ERROR', `后端返回了非预期的错误响应（HTTP ${response.status}）`, {
    status: response.status,
    shouldReport: true,
  })
}

/**
 * 真实 `ChatTransport` 实现：装配鉴权头、请求追踪 id，转发给浏览器 `fetch`，
 * 并把网络失败 / 非 2xx 响应统一归一成 `AppError`。
 *
 * 成功路径（2xx）直接把 `Response` 原样交回给上层——`sse.ts` 要自己读
 * `response.body` 这条流，这里绝不能提前 `await response.json()` 或
 * `.text()`，否则流就被消费掉了。
 */
export function createFetchTransport(): ChatTransport {
  return async (req, signal) => {
    const base = resolveApiBaseUrl()
    const headers: Record<string, string> = {
      ...buildAuthHeaders(req.auth ?? 'merchant'),
      'X-Request-Id': crypto.randomUUID(),
    }
    if (req.accept) headers.Accept = req.accept
    if (req.body !== undefined) headers['Content-Type'] = 'application/json'

    let response: Response
    try {
      response = await fetch(`${base}${req.path}`, {
        method: req.method,
        headers,
        body: req.body === undefined ? undefined : JSON.stringify(req.body),
        signal,
        credentials: 'omit',
        cache: 'no-store',
      })
    } catch (cause) {
      // AbortError → CANCELLED；TypeError（离线、DNS 失败、CORS 预检失败，
      // 浏览器都不给区分）→ NETWORK。
      throw toAppError(cause)
    }

    if (!response.ok) throw await toHttpError(response)
    return response
  }
}

export async function resolveTransport(): Promise<ChatTransport> {
  if (override) return override
  if (cached) return cached

  if (!isMockEnabled()) {
    cached = createFetchTransport()
    return cached
  }

  const { createMockTransport } = await import('./mock/transport')
  cached = createMockTransport()
  return cached
}
