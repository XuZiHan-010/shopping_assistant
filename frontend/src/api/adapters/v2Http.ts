/**
 * v2 商家端点共用的请求与错误转换。
 *
 * 单独成文件而不是继续在每个 Adapter 里各写一份：错误信封是全后端统一的
 * `ErrorResponse`，各 Adapter 各判一次迟早会出现「这个 Adapter 认得 422，
 * 那个把它当成未知错误」。`session.ts` 早于本模块落地，仍带着自己的一份副本，
 * 由商家端 v2 迁移在接入会话 Store 时一并收敛。
 */
import { resolveApiBaseUrl } from '@/api/client'
import { AppError, toAppError } from '@/api/errors'
import type { components } from '@/api/generated'

type ErrorResponsePayload = components['schemas']['ErrorResponse']

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

/** 带会话头的 v2 请求；非 2xx 一律转成 `AppError`，调用方按 `code` 分支。 */
export async function merchantRequest(
  path: string,
  sessionId: string,
  init: RequestInit = {},
): Promise<Response> {
  const base = resolveApiBaseUrl()
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), 'X-Session-Id': sessionId },
      credentials: 'omit',
      // 草稿详情带一次性审批证据，后端已声明 no-store；这里再确保不进 HTTP 缓存。
      cache: 'no-store',
    })
  } catch (cause) {
    throw toAppError(cause)
  }
  if (!response.ok) throw await toHttpError(response)
  return response
}

/** 把 `cursor` / `limit` 这类可选查询参数拼成串；空值不出现在 URL 里。 */
export function queryString(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}
