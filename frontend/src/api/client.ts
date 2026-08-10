/**
 * API 基础地址的唯一读取点。
 *
 * F0 只负责解析基础地址；HTTP 客户端、鉴权头和统一错误处理在 F3 补进本文件
 * （AGENTS.md §7.5 把这些职责都归给 api/client.ts）。
 */
import { AppError } from './errors'

/** 配置缺失或非法时抛出，由全局错误区展示。是 `AppError` 的 `CONFIG` 特化。 */
export class ApiConfigError extends AppError {
  constructor(message: string) {
    super('CONFIG', message)
    this.name = 'ApiConfigError'
  }
}

/**
 * 解析后端基础地址。
 *
 * 刻意**不提供**同源 `/api` 回退。生产部署里 Caddy 只服务静态文件、不代理
 * `/api`（AGENTS.md §十四：Backend 公开 + 严格 CORS，不引入反向代理容器），
 * 所以有回退时漏配这个变量会让请求打到静态服务器上拿 404，表现成「接口坏了」
 * 而不是「配置漏了」。响亮地失败比安静地走错路好查得多。
 *
 * 本地开发由 `.env.development` 提供默认值。
 */
export function resolveApiBaseUrl(
  raw: string | undefined = import.meta.env.VITE_API_BASE_URL,
): string {
  const value = raw?.trim()

  if (!value) {
    throw new ApiConfigError(
      '缺少 VITE_API_BASE_URL 配置，前端不知道该把请求发到哪个后端。' +
        '请参考 .env.example 配置该变量后重新构建。',
    )
  }

  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw new ApiConfigError(`VITE_API_BASE_URL 不是合法的绝对地址：${value}`)
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new ApiConfigError(`VITE_API_BASE_URL 只支持 http 或 https：${value}`)
  }

  // 统一去掉结尾斜杠，调用方拼路径时不必再判断。
  return value.replace(/\/+$/, '')
}
