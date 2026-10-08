/**
 * 统一错误类型：把后端 `ErrorResponse`、网络失败、取消、契约违反等一切错误来源
 * 归一成同一种形状（前端方案 §10）。
 *
 * 下游（composables、store、组件）只认 `AppError`，不需要各自去拆 fetch 抛出的
 * 异常、`DOMException`，也不用直接消费 `generated.ts` 的错误 schema——这是
 * `describeError` 能对外暴露干净类型、而不是让每个调用点自己解析原始载荷的前提。
 */
import type { components } from '@/api/generated'

type BackendErrorCode = components['schemas']['ErrorCode']
type ErrorResponsePayload = components['schemas']['ErrorResponse']

/** 前端自身产生、后端契约里没有的错误码。 */
export type LocalErrorCode = 'CONFIG' | 'NETWORK' | 'CANCELLED' | 'STREAM_INTERRUPTED' | 'CONTRACT'

export type AppErrorCode = BackendErrorCode | LocalErrorCode

/**
 * `generated.ts` 里的 `ErrorCode` 只是联合类型，没有运行时表示，无法在运行时
 * 直接判断某个字符串是否属于它。这份列表是它的运行时镜像，用来校验后端实际
 * 返回的 `code` 是否在册。
 *
 * `Record<BackendErrorCode, true>` 同时检查缺项和多余项；后端新增、删除或重命名
 * 错误码时，运行时白名单必须同步，否则 typecheck 报错。另有 OpenAPI 全枚举回归测试。
 */
const KNOWN_BACKEND_ERROR_CODES = {
  AUTH_REQUIRED: true,
  MERCHANT_SCOPE_VIOLATION: true,
  NOT_FOUND: true,
  METHOD_NOT_ALLOWED: true,
  INVALID_REQUEST: true,
  IDEMPOTENCY_KEY_REUSED: true,
  REQUEST_IN_PROGRESS: true,
  DAILY_REPORT_FEEDBACK_CONFLICT: true,
  DATA_SOURCE_UNAVAILABLE: true,
  EXPORT_LINK_EXPIRED: true,
  RATE_LIMITED: true,
  LLM_BUDGET_EXCEEDED: true,
  FORBIDDEN: true,
  HTTP_ERROR: true,
  INTERNAL_ERROR: true,
  INVALID_WIKI_PATH: true,
  WIKI_READ_ONLY: true,
  INVALID_FILE_TYPE: true,
  INVALID_WIKI_PARENT: true,
  WIKI_NODE_EXISTS: true,
  WIKI_NODE_NOT_FOUND: true,
  WIKI_DIRECTORY_NOT_EMPTY: true,
  WIKI_VERSION_REQUIRED: true,
  WIKI_VERSION_CONFLICT: true,
  WIKI_DOCUMENT_TOO_LARGE: true,
  INVALID_WIKI_ENCODING: true,
  INVALID_WIKI_CONTENT: true,
  WIKI_IO_ERROR: true,
  SESSION_REQUIRED: true,
  SESSION_INVALID: true,
  SESSION_ROLE_MISMATCH: true,
  CUSTOMER_BINDING_REQUIRED: true,
  SESSION_ALREADY_BOUND: true,
  RESOURCE_FORBIDDEN: true,
  PRODUCT_NOT_IN_SCOPE: true,
  INSUFFICIENT_STOCK: true,
  ILLEGAL_STATE_TRANSITION: true,
  VERSION_CONFLICT: true,
  DRAFT_EXPIRED: true,
  GUARDRAIL_REJECTED: true,
  CONFIRMATION_REQUIRED: true,
  INVALID_CURSOR: true,
} as const satisfies Record<BackendErrorCode, true>

const KNOWN_BACKEND_ERROR_CODE_SET: ReadonlySet<string> = new Set(
  Object.keys(KNOWN_BACKEND_ERROR_CODES),
)

export interface AppErrorInit {
  status?: number
  requestId?: string
  retryable?: boolean
  details?: unknown
  shouldReport?: boolean
  cause?: unknown
}

/** 所有前端错误处理的唯一落点。见 `describeError`（`src/utils/errorCopy.ts`）取展示文案。 */
export class AppError extends Error {
  readonly code: AppErrorCode
  readonly status?: number
  readonly requestId?: string
  readonly retryable: boolean
  readonly details?: unknown
  /** 是否应上报（日志/监控）。前端自身缺陷类错误（契约违反等）恒为 true。 */
  readonly shouldReport: boolean

  constructor(code: AppErrorCode, message: string, init: AppErrorInit = {}) {
    super(message, init.cause !== undefined ? { cause: init.cause } : undefined)
    this.name = 'AppError'
    this.code = code
    this.status = init.status
    this.requestId = init.requestId
    this.retryable = init.retryable ?? false
    this.details = init.details
    this.shouldReport = init.shouldReport ?? false
  }

  /**
   * 把后端 `ErrorResponse` 载荷归一为 `AppError`。
   *
   * `retryable` 直接取载荷的值，不由前端表推断——后端才知道这次失败是否值得重试。
   * `code` 不在已知集合内时（后端加了新码但前端还没跟上，或返回了根本不认识的
   * 字符串）降级为 `HTTP_ERROR` 并强制 `shouldReport = true`：遇到表中没有的码时
   * 按通用错误展示并上报（前端方案 §10）。
   */
  static fromErrorResponse(payload: ErrorResponsePayload, status?: number): AppError {
    const isKnown = KNOWN_BACKEND_ERROR_CODE_SET.has(payload.code)
    const code: AppErrorCode = isKnown ? payload.code : 'HTTP_ERROR'

    return new AppError(code, payload.message, {
      status,
      requestId: payload.request_id,
      retryable: payload.retryable,
      details: payload.details,
      shouldReport: !isKnown,
    })
  }

  /** 网络层失败（连接被拒、DNS 失败、离线等），值得让用户重试。 */
  static fromNetwork(cause: unknown): AppError {
    const detail = cause instanceof Error ? cause.message : String(cause)
    return new AppError('NETWORK', `网络请求失败：${detail}`, {
      retryable: true,
      cause,
    })
  }
}

/**
 * 兜底漏斗：把 `catch` 到的任意异常归一为 `AppError`。
 *
 * - 已是 `AppError`：原样返回，不重新包装。
 * - `name === 'AbortError'` 的 `DOMException`：`AbortController.abort()` 触发的
 *   取消，归一为 `CANCELLED`。
 * - `TypeError`：`fetch` 在网络层失败（连接被拒、离线等）时抛出的类型，归一为
 *   `NETWORK`。
 * - 其余：无法识别的异常本身就是前端的缺陷，归一为 `INTERNAL_ERROR` 并上报。
 */
export function toAppError(error: unknown): AppError {
  if (error instanceof AppError) return error

  if (error instanceof DOMException && error.name === 'AbortError') {
    return new AppError('CANCELLED', '请求已取消', { cause: error })
  }

  if (error instanceof TypeError) {
    return AppError.fromNetwork(error)
  }

  const message = error instanceof Error ? error.message : String(error)
  return new AppError('INTERNAL_ERROR', message || '发生未知错误', {
    shouldReport: true,
    cause: error,
  })
}
