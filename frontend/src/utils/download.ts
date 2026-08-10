const CLOCK_SKEW_MS = 30_000

export interface ExportExpiry {
  expired: boolean
  minutesRemaining: number
}

export function buildExportHref(apiBaseUrl: string, url: string): string {
  if (!url.startsWith('/api/exports/')) throw new Error('导出链接格式无效')
  return `${apiBaseUrl.replace(/\/$/, '')}${url}`
}

export function exportExpiry(expiresAt: string, now = new Date()): ExportExpiry {
  const timestamp = Date.parse(expiresAt)
  const remaining = timestamp - now.getTime() - CLOCK_SKEW_MS
  if (!Number.isFinite(timestamp) || remaining <= 0) return { expired: true, minutesRemaining: 0 }

  return { expired: false, minutesRemaining: Math.ceil(remaining / 60_000) }
}
