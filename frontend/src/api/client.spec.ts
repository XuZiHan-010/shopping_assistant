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

    try {
      resolveApiBaseUrl(value)
      expect.unreachable('resolveApiBaseUrl 应该抛出 ApiConfigError')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiConfigError)
      expect((error as ApiConfigError).code).toBe('CONFIG')
      expect((error as ApiConfigError).reason).toBe('MISSING_BASE_URL')
    }
  })

  it('拒绝相对路径，reason 稳定为 INVALID_BASE_URL 并带上原始值', () => {
    try {
      resolveApiBaseUrl('/api')
      expect.unreachable('resolveApiBaseUrl 应该抛出 ApiConfigError')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiConfigError)
      expect((error as ApiConfigError).reason).toBe('INVALID_BASE_URL')
      expect((error as ApiConfigError).value).toBe('/api')
    }
  })

  it('拒绝非 http(s) 协议，reason 稳定为 UNSUPPORTED_PROTOCOL', () => {
    try {
      resolveApiBaseUrl('ftp://api.example.com')
      expect.unreachable('resolveApiBaseUrl 应该抛出 ApiConfigError')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiConfigError)
      expect((error as ApiConfigError).reason).toBe('UNSUPPORTED_PROTOCOL')
      expect((error as ApiConfigError).value).toBe('ftp://api.example.com')
    }
  })

  it('只暴露稳定的 code/reason/value，不把展示文案编进异常消息——具体语言由 errorCopy 按当前 locale 翻译', () => {
    try {
      resolveApiBaseUrl('')
      expect.unreachable('resolveApiBaseUrl 应该抛出 ApiConfigError')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiConfigError)
      const configError = error as ApiConfigError
      expect(configError.code).toBe('CONFIG')
      expect(typeof configError.reason).toBe('string')
      // details 是 describeError/errorCopy 消费的稳定结构化数据，不是拼好的中文句子。
      expect(configError.details).toEqual({ reason: 'MISSING_BASE_URL', value: undefined })
    }
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
