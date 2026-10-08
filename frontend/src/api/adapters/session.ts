/**
 * 商家会话 Adapter：`POST /v2/merchant/sessions`（Bearer）与
 * `DELETE /v2/merchant/sessions/current`（`X-Session-Id`）。
 *
 * 范围按 N1 D Task 7 收窄：只封装这两条请求本身，把 `generated.ts` 类型转成
 * 领域类型，不接入 Store、不改任何页面——切换商家流程与会话 Store 接入属于
 * `n2-merchant-vue-v2-migration` Task 2。因此本模块刻意不读
 * `credentials.ts` 的凭证注册表，Token 与会话 ID 都由调用方显式传入。
 */
import { resolveApiBaseUrl } from '@/api/client'
import { AppError, toAppError } from '@/api/errors'
import type { components } from '@/api/generated'

type RawMerchantSessionCreateResponse = components['schemas']['MerchantSessionCreateResponse']
type ErrorResponsePayload = components['schemas']['ErrorResponse']

export interface MerchantSession {
  sessionId: string
  role: 'MERCHANT'
  expiresAt: string
  merchantDisplayName: string
  /** 本店顾客端店铺标识（D-N5-4）：后端从已验证会话解析，只用来拼「顾客视角」链接。 */
  shopSlug: string
}

function toMerchantSession(raw: RawMerchantSessionCreateResponse): MerchantSession {
  return {
    sessionId: raw.session_id,
    role: raw.role,
    expiresAt: raw.expires_at,
    merchantDisplayName: raw.merchant_display_name,
    shopSlug: raw.shop_slug,
  }
}

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

async function request(path: string, init: RequestInit): Promise<Response> {
  const base = resolveApiBaseUrl()
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      ...init,
      credentials: 'omit',
      cache: 'no-store',
    })
  } catch (cause) {
    throw toAppError(cause)
  }
  if (!response.ok) throw await toHttpError(response)
  return response
}

/**
 * 用商家演示 Bearer Token 换取一个会话。**Token 只在这一次调用里使用**，
 * 调用方此后应改用返回的 `sessionId`，不再重复传 Token（D8②）。
 */
export async function createMerchantSession(merchantToken: string): Promise<MerchantSession> {
  const response = await request('/api/v2/merchant/sessions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${merchantToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  })
  const payload = (await response.json()) as RawMerchantSessionCreateResponse
  return toMerchantSession(payload)
}

/** 注销当前商家会话；204 无响应体，注销后复用该会话 ID 会得到 401 SESSION_INVALID。 */
export async function revokeMerchantSession(sessionId: string): Promise<void> {
  await request('/api/v2/merchant/sessions/current', {
    method: 'DELETE',
    headers: { 'X-Session-Id': sessionId },
  })
}
