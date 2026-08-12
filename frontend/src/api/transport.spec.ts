import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setCredentialProvider } from './credentials'
import { createFetchTransport } from './transport'

const BASE_URL = 'http://127.0.0.1:8000'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** fetch 的第二个入参（RequestInit），headers 在 createFetchTransport 里就是普通对象。 */
function requestInit(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): RequestInit {
  return fetchMock.mock.calls[callIndex][1] as RequestInit
}

describe('createFetchTransport', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    setCredentialProvider(() => ({ merchantToken: 'demo-token' }))
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    setCredentialProvider(undefined)
  })

  it('GET 不带 Content-Type，POST 带且 body 已序列化', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const transport = createFetchTransport()

    await transport({ path: '/api/conversations', method: 'GET' }, new AbortController().signal)
    const getInit = requestInit(fetchMock, 0)
    expect((getInit.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    expect(getInit.body).toBeUndefined()

    await transport(
      { path: '/api/chat', method: 'POST', body: { message: '你好' } },
      new AbortController().signal,
    )
    const postInit = requestInit(fetchMock, 1)
    expect((postInit.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(postInit.body).toBe(JSON.stringify({ message: '你好' }))
  })

  it('每次请求带唯一 X-Request-Id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const transport = createFetchTransport()

    await transport({ path: '/api/conversations', method: 'GET' }, new AbortController().signal)
    await transport({ path: '/api/conversations', method: 'GET' }, new AbortController().signal)

    const id1 = (requestInit(fetchMock, 0).headers as Record<string, string>)['X-Request-Id']
    const id2 = (requestInit(fetchMock, 1).headers as Record<string, string>)['X-Request-Id']
    expect(id1).toBeTruthy()
    expect(id2).toBeTruthy()
    expect(id1).not.toBe(id2)
  })

  it('2xx 响应返回后 body 流仍可读', async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: done\ndata: {}\n\n'))
        controller.close()
      },
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
      )
    vi.stubGlobal('fetch', fetchMock)
    const transport = createFetchTransport()

    const response = await transport(
      { path: '/api/chat', method: 'POST', body: {} },
      new AbortController().signal,
    )
    expect(response.body).not.toBeNull()
    const chunk = await response.body!.getReader().read()
    expect(chunk.done).toBe(false)
  })

  it('401 的 JSON body 转成带 requestId 的 AppError', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(
          { code: 'AUTH_REQUIRED', message: '登录已过期', request_id: 'req-401', retryable: false },
          401,
        ),
      )
    vi.stubGlobal('fetch', fetchMock)
    const transport = createFetchTransport()

    await expect(
      transport({ path: '/api/chat', method: 'POST', body: {} }, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'AUTH_REQUIRED', requestId: 'req-401', status: 401 })
  })

  it('非 JSON body 的 502 转成 HTTP_ERROR 并保留 status', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('<html>Bad Gateway</html>', {
        status: 502,
        headers: { 'content-type': 'text/html' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const transport = createFetchTransport()

    await expect(
      transport({ path: '/api/conversations', method: 'GET' }, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'HTTP_ERROR', status: 502 })
  })

  it('fetch 抛 TypeError 转成 NETWORK', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)
    const transport = createFetchTransport()

    await expect(
      transport({ path: '/api/conversations', method: 'GET' }, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'NETWORK' })
  })

  it('req.auth 缺省为 merchant，缺凭证时在发出请求前就拒绝', async () => {
    setCredentialProvider(() => ({}))
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const transport = createFetchTransport()

    await expect(
      transport({ path: '/api/conversations', method: 'GET' }, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'AUTH_REQUIRED' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
