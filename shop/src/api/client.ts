/**
 * API 基础地址与 HTTP 传输的唯一入口。
 *
 * 刻意**不提供**同源 `/api` 回退：shop 与 Backend 是两个独立公开服务，浏览器直连 Backend
 * （AGENTS.md §十一，不引入反向代理）。漏配 `NEXT_PUBLIC_API_BASE_URL` 时回退同源只会让请求
 * 打到 Next.js 上拿 404，表现成「接口坏了」而不是「配置漏了」，所以响亮地失败。
 */
import { ApiConfigError, ApiError, NetworkError } from './errors'

export { ApiConfigError }

export function resolveApiBaseUrl(raw: string | undefined): string {
  const value = raw?.trim()
  if (!value) throw new ApiConfigError('MISSING_BASE_URL')

  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw new ApiConfigError('INVALID_BASE_URL', value)
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new ApiConfigError('UNSUPPORTED_PROTOCOL', value)
  }
  return value.replace(/\/+$/, '')
}

/** 必须写成 `process.env.NEXT_PUBLIC_*` 的静态形式，Next 才会在构建期内联。 */
export function apiBaseUrl(): string {
  return resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL)
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  /** 顾客会话 ID，只进 `X-Session-Id` 请求头，绝不进 URL。 */
  sessionId?: string | null
  headers?: Record<string, string>
  signal?: AbortSignal
}

/** 组装请求；SSE 与普通 JSON 共用，区别只在 `Accept`。 */
export async function rawRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.sessionId) headers['X-Session-Id'] = options.sessionId

  let response: Response
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof ApiConfigError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new NetworkError(error)
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, body)
  }
  return response
}

export async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await rawRequest(path, options)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
