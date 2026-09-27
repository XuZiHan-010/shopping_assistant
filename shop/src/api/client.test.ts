import { describe, expect, it } from 'vitest'
import { ApiConfigError, resolveApiBaseUrl } from './client'

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
