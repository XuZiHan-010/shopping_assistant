import { describe, expect, it } from 'vitest'

import { AppError, toAppError } from './errors'

describe('toAppError', () => {
  it('AbortError 归一为 CANCELLED', () => {
    expect(toAppError(new DOMException('', 'AbortError')).code).toBe('CANCELLED')
  })

  it('已是 AppError 时原样返回，不重新包装', () => {
    const original = new AppError('NETWORK', '网络失败')
    expect(toAppError(original)).toBe(original)
  })

  it('TypeError 归一为 NETWORK，且标记可重试', () => {
    const error = toAppError(new TypeError('Failed to fetch'))
    expect(error.code).toBe('NETWORK')
    expect(error.retryable).toBe(true)
  })

  it('未识别的异常归一为 INTERNAL_ERROR 并上报', () => {
    const error = toAppError('plain string thrown')
    expect(error.code).toBe('INTERNAL_ERROR')
    expect(error.shouldReport).toBe(true)
  })
})

describe('AppError.fromErrorResponse', () => {
  it('retryable 以后端返回为准，不由前端表推断', () => {
    const error = AppError.fromErrorResponse(
      {
        code: 'RATE_LIMITED',
        message: '请求过多',
        request_id: 'r-1',
        details: [],
        retryable: true,
      },
      429,
    )
    expect(error.retryable).toBe(true)
    expect(error.requestId).toBe('r-1')
    expect(error.status).toBe(429)
  })

  it('未知错误码不被静默吞掉', () => {
    const error = AppError.fromErrorResponse(
      {
        code: 'SOMETHING_NEW',
        message: 'x',
        request_id: 'r-2',
        details: [],
        retryable: false,
      } as never,
      418,
    )
    expect(error.code).toBe('HTTP_ERROR')
    expect(error.shouldReport).toBe(true)
  })

  it('已知错误码原样保留，且不强行上报', () => {
    const error = AppError.fromErrorResponse(
      {
        code: 'AUTH_REQUIRED',
        message: '请重新登录',
        request_id: 'r-3',
        details: [],
        retryable: false,
      },
      401,
    )
    expect(error.code).toBe('AUTH_REQUIRED')
    expect(error.shouldReport).toBe(false)
  })

  it('知识库路径错误保留业务错误码，供中文文案展示', () => {
    const error = AppError.fromErrorResponse(
      {
        code: 'WIKI_READ_ONLY',
        message: '记忆目录只读',
        request_id: 'r-4',
        details: [],
        retryable: false,
      },
      403,
    )

    expect(error.code).toBe('WIKI_READ_ONLY')
    expect(error.shouldReport).toBe(false)
  })
})

describe('AppError.fromNetwork', () => {
  it('归一为 NETWORK 且可重试', () => {
    const error = AppError.fromNetwork(new TypeError('Failed to fetch'))
    expect(error.code).toBe('NETWORK')
    expect(error.retryable).toBe(true)
  })
})
