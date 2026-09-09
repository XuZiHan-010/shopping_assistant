import { describe, expect, it } from 'vitest'

import { AppError } from '@/api/errors'

import { buildExportHref, exportExpiry } from './download'

describe('buildExportHref', () => {
  it('只为后端签发的相对导出路径添加 API 域名', () => {
    expect(buildExportHref('https://api.example.test/', '/api/exports/e-1?signature=abc')).toBe(
      'https://api.example.test/api/exports/e-1?signature=abc',
    )
  })

  it('拒绝非导出路径，避免把服务端字符串直接变成跳转链接；只暴露稳定 code/details，不硬编码中文异常文案', () => {
    try {
      buildExportHref('https://api.example.test', 'https://attacker.test')
      expect.unreachable('buildExportHref 应该抛出错误')
    } catch (error) {
      expect(error).toBeInstanceOf(AppError)
      const appError = error as AppError
      expect(appError.code).toBe('CONTRACT')
      expect(appError.details).toMatchObject({
        reason: 'INVALID_EXPORT_URL',
        url: 'https://attacker.test',
      })
    }
  })
})

describe('exportExpiry', () => {
  it('为未过期链接预留 30 秒时钟偏移', () => {
    expect(exportExpiry('2026-08-07T10:02:00.000Z', new Date('2026-08-07T10:00:00.000Z'))).toEqual({
      expired: false,
      minutesRemaining: 2,
    })
  })

  it('把剩余不足 30 秒的链接视为过期', () => {
    expect(exportExpiry('2026-08-07T10:00:20.000Z', new Date('2026-08-07T10:00:00.000Z'))).toEqual({
      expired: true,
      minutesRemaining: 0,
    })
  })
})
