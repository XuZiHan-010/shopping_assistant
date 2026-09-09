import { AppError } from '@/api/errors'

const CLOCK_SKEW_MS = 30_000

export interface ExportExpiry {
  expired: boolean
  minutesRemaining: number
}

/**
 * 校验并拼出导出下载的完整地址。只接受后端签发的 `/api/exports/...` 相对
 * 路径，不接受任意 URL——不然服务端字符串会被直接当成跳转链接（开放重定向
 * 风险）。校验失败视为前端自身的契约违反：只暴露稳定的 `CONTRACT` 错误码
 * 和结构化 `details`，具体展示文案交给 `errorCopy`（`src/utils/errorCopy.ts`）
 * 按当前语言翻译，调用方和测试都不应该直接比较 `.message` 的具体文字。
 */
export function buildExportHref(apiBaseUrl: string, url: string): string {
  if (!url.startsWith('/api/exports/')) {
    throw new AppError('CONTRACT', `Invalid export link: ${url}`, {
      details: { reason: 'INVALID_EXPORT_URL', url },
      shouldReport: true,
    })
  }
  return `${apiBaseUrl.replace(/\/$/, '')}${url}`
}

export function exportExpiry(expiresAt: string, now = new Date()): ExportExpiry {
  const timestamp = Date.parse(expiresAt)
  const remaining = timestamp - now.getTime() - CLOCK_SKEW_MS
  if (!Number.isFinite(timestamp) || remaining <= 0) return { expired: true, minutesRemaining: 0 }

  return { expired: false, minutesRemaining: Math.ceil(remaining / 60_000) }
}
