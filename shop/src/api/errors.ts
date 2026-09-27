import type { components } from './generated'

type ErrorResponse = components['schemas']['ErrorResponse']
export type ApiErrorCode = ErrorResponse['code']

export type ApiConfigErrorReason = 'MISSING_BASE_URL' | 'INVALID_BASE_URL' | 'UNSUPPORTED_PROTOCOL'

/** 配置缺失或非法：构建/部署问题，响亮失败，不回退同源 `/api`。 */
export class ApiConfigError extends Error {
  readonly reason: ApiConfigErrorReason
  readonly value?: string

  constructor(reason: ApiConfigErrorReason, value?: string) {
    super(`ApiConfigError: ${reason}${value !== undefined ? ` (${value})` : ''}`)
    this.name = 'ApiConfigError'
    this.reason = reason
    this.value = value
  }
}

/** 后端返回的统一错误结构（ErrorResponse）。 */
export class ApiError extends Error {
  readonly status: number
  readonly code: ApiErrorCode
  readonly requestId: string | null
  readonly details: Record<string, unknown>[]
  readonly retryable: boolean

  constructor(status: number, body: Partial<ErrorResponse> | null) {
    super(body?.message ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = body?.code ?? 'HTTP_ERROR'
    this.requestId = body?.request_id ?? null
    this.details = (body?.details as Record<string, unknown>[] | undefined) ?? []
    this.retryable = body?.retryable ?? false
  }
}

/** 请求没有拿到任何 HTTP 响应（断网、CORS 拒绝、超时）。重试必须复用同一个 client_request_id。 */
export class NetworkError extends Error {
  constructor(cause?: unknown) {
    super('NetworkError')
    this.name = 'NetworkError'
    this.cause = cause
  }
}
