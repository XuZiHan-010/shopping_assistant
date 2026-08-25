import { describe, expect, it } from 'vitest'

import { ApiConfigError, resolveApiBaseUrl, resolveViewerToken } from './client'

describe('resolveApiBaseUrl', () => {
  it('接受合法的绝对地址', () => {
    expect(resolveApiBaseUrl('https://api.example.com')).toBe('https://api.example.com')
  })

  it('去掉结尾斜杠，调用方拼路径时不必再判断', () => {
    expect(resolveApiBaseUrl('https://api.example.com/')).toBe('https://api.example.com')
    expect(resolveApiBaseUrl('http://127.0.0.1:8000///')).toBe('http://127.0.0.1:8000')
  })

  it.each([undefined, '', '   '])('配置缺失时报错而不是静默回退到同源 (%s)', (value) => {
    // 有同源回退时，生产漏配会让请求打到静态服务器上拿 404，
    // 表现成「接口坏了」而不是「配置漏了」。
    expect(() => resolveApiBaseUrl(value)).toThrow(ApiConfigError)
    expect(() => resolveApiBaseUrl(value)).toThrow(/VITE_API_BASE_URL/)
  })

  it('拒绝相对路径', () => {
    expect(() => resolveApiBaseUrl('/api')).toThrow(ApiConfigError)
  })

  it('拒绝非 http(s) 协议', () => {
    expect(() => resolveApiBaseUrl('ftp://api.example.com')).toThrow(/http/)
  })

  it('错误信息是中文，可直接展示给用户', () => {
    expect(() => resolveApiBaseUrl('')).toThrow(/缺少|配置/)
  })
})

describe('resolveViewerToken', () => {
  it.each([undefined, '', '   '])('未配置时返回 undefined，不是空字符串 (%s)', (value) => {
    // 与 resolveApiBaseUrl 的「缺失即报错」刻意不同：只读令牌是可选功能，
    // 没配置时应当让调用方判断"不展示这个入口"，而不是让整个页面炸掉。
    expect(resolveViewerToken(value)).toBeUndefined()
  })

  it('配置了就原样返回，两端去掉多余空白', () => {
    expect(resolveViewerToken('  viewer-token-value  ')).toBe('viewer-token-value')
  })
})
