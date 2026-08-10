import { describe, expect, it } from 'vitest'

import { AppError, type AppErrorCode } from '@/api/errors'
import type { components } from '@/api/generated'

import { describeError } from './errorCopy'

const BACKEND_CODES = [
  'AUTH_REQUIRED',
  'MERCHANT_SCOPE_VIOLATION',
  'NOT_FOUND',
  'METHOD_NOT_ALLOWED',
  'INVALID_REQUEST',
  'IDEMPOTENCY_KEY_REUSED',
  'REQUEST_IN_PROGRESS',
  'DATA_SOURCE_UNAVAILABLE',
  'EXPORT_LINK_EXPIRED',
  'RATE_LIMITED',
  'LLM_BUDGET_EXCEEDED',
  'FORBIDDEN',
  'HTTP_ERROR',
  'INTERNAL_ERROR',
] as const satisfies readonly components['schemas']['ErrorCode'][]

describe('describeError', () => {
  it.each([...BACKEND_CODES, 'CONFIG', 'NETWORK', 'CANCELLED', 'STREAM_INTERRUPTED', 'CONTRACT'])(
    '%s 有非空中文文案',
    (code) => {
      const copy = describeError(new AppError(code as AppErrorCode, 'x'))
      expect(copy.title.length).toBeGreaterThan(0)
      expect(copy.detail.length).toBeGreaterThan(0)
    },
  )

  it('LLM_BUDGET_EXCEEDED 与普通 5xx 文案不同', () => {
    expect(describeError(new AppError('LLM_BUDGET_EXCEEDED', 'x')).title).not.toBe(
      describeError(new AppError('INTERNAL_ERROR', 'x')).title,
    )
  })

  it('前端自身缺陷类错误只上报，不提示用户重试', () => {
    for (const code of ['METHOD_NOT_ALLOWED', 'IDEMPOTENCY_KEY_REUSED', 'CONTRACT'] as const) {
      expect(describeError(new AppError(code, 'x')).surface).toBe('silent-report')
    }
  })

  it('AUTH_REQUIRED 指向重新选择商家', () => {
    expect(describeError(new AppError('AUTH_REQUIRED', 'x')).action).toBe('reselect-merchant')
  })

  it('EXPORT_LINK_EXPIRED 指向重新提问', () => {
    expect(describeError(new AppError('EXPORT_LINK_EXPIRED', 'x')).action).toBe('reask')
  })
})
