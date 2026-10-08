import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'

import { createMerchantSession, revokeMerchantSession } from './session'

const BASE_URL = 'http://127.0.0.1:8000'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function errorResponse(code: string, status: number): Response {
  return jsonResponse(
    { code, message: 'boom', request_id: 'req-1', details: [], retryable: false },
    status,
  )
}

describe('session adapter', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('createMerchantSession 用 Bearer 换会话并转成领域类型', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          session_id: 'a'.repeat(43),
          role: 'MERCHANT',
          expires_at: '2026-09-23T00:00:00Z',
          merchant_display_name: 'Borough商家100',
          shop_slug: 'borough-demo-100',
        },
        201,
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const session = await createMerchantSession('demo-token')

    expect(session).toEqual({
      sessionId: 'a'.repeat(43),
      role: 'MERCHANT',
      expiresAt: '2026-09-23T00:00:00Z',
      merchantDisplayName: 'Borough商家100',
      shopSlug: 'borough-demo-100',
    })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/sessions`)
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer demo-token')
    expect(init.body).toBe(JSON.stringify({}))
  })

  it('createMerchantSession 对 401 AUTH_REQUIRED 抛出 AppError', async () => {
    const fetchMock = vi.fn().mockResolvedValue(errorResponse('AUTH_REQUIRED', 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(createMerchantSession('bad-token')).rejects.toMatchObject({
      code: 'AUTH_REQUIRED',
      status: 401,
    } satisfies Partial<AppError>)
  })

  it('revokeMerchantSession 用 X-Session-Id 注销', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await revokeMerchantSession('session-token-value')

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/sessions/current`)
    expect(init.method).toBe('DELETE')
    expect((init.headers as Record<string, string>)['X-Session-Id']).toBe('session-token-value')
  })

  it('revokeMerchantSession 对 401 SESSION_INVALID 抛出 AppError', async () => {
    const fetchMock = vi.fn().mockResolvedValue(errorResponse('SESSION_INVALID', 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(revokeMerchantSession('expired-session')).rejects.toMatchObject({
      code: 'SESSION_INVALID',
      status: 401,
    } satisfies Partial<AppError>)
  })

  it('403 SESSION_ROLE_MISMATCH 同样归一为 AppError', async () => {
    const fetchMock = vi.fn().mockResolvedValue(errorResponse('SESSION_ROLE_MISMATCH', 403))
    vi.stubGlobal('fetch', fetchMock)

    await expect(revokeMerchantSession('customer-session')).rejects.toMatchObject({
      code: 'SESSION_ROLE_MISMATCH',
      status: 403,
    } satisfies Partial<AppError>)
  })
})
