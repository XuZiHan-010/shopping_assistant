import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiConfigError, rawRequest, resolveApiBaseUrl, setRequestLocale } from './client'

describe('resolveApiBaseUrl', () => {
  it('NEXT_PUBLIC_API_BASE_URL 缺失时抛错，不回退同源', () => {
    expect(() => resolveApiBaseUrl(undefined)).toThrow(ApiConfigError)
    expect(() => resolveApiBaseUrl('   ')).toThrow(ApiConfigError)
  })

  it('非法地址与非 http(s) 协议抛错', () => {
    expect(() => resolveApiBaseUrl('not a url')).toThrow(ApiConfigError)
    expect(() => resolveApiBaseUrl('ftp://example.com')).toThrow(ApiConfigError)
  })

  it('去掉结尾斜杠，调用方拼路径时不必再判断', () => {
    expect(resolveApiBaseUrl('https://api.example.com//')).toBe('https://api.example.com')
  })
})

describe('rawRequest 的请求语言', () => {
  afterEach(() => { setRequestLocale('zh-CN'); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

  it('调用方没给语言时补当前界面语言；显式给了请求头时不覆盖', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.test')
    const fetcher = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetcher)

    setRequestLocale('en-US')
    await rawRequest('/api/health')
    await rawRequest('/api/health', { headers: { 'accept-language': 'zh-CN' } })

    const headers = fetcher.mock.calls.map(call => (call as unknown as [string, RequestInit])[1].headers as Record<string, string>)
    expect(headers[0]!['Accept-Language']).toBe('en-US')
    expect(headers[1]!['accept-language']).toBe('zh-CN')
    expect(headers[1]!['Accept-Language']).toBeUndefined()
  })
})

describe('rawRequest 的追踪 ID（N5 B Task 3）', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

  it('每次请求带唯一 X-Request-Id；调用方显式给了就不覆盖', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.test')
    const fetcher = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetcher)

    await rawRequest('/api/health')
    await rawRequest('/api/health')
    await rawRequest('/api/health', { headers: { 'x-request-id': 'trace-abc' } })

    const headers = fetcher.mock.calls.map(call => (call as unknown as [string, RequestInit])[1].headers as Record<string, string>)
    expect(headers[0]!['X-Request-Id']).toMatch(/^[A-Za-z0-9._:-]{1,128}$/)
    expect(headers[0]!['X-Request-Id']).not.toBe(headers[1]!['X-Request-Id'])
    expect(headers[2]!['x-request-id']).toBe('trace-abc')
    expect(headers[2]!['X-Request-Id']).toBeUndefined()
  })
})
