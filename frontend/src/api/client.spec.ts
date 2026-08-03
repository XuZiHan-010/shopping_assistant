import { describe, expect, it } from 'vitest'

import { ApiConfigError, resolveApiBaseUrl } from './client'

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
