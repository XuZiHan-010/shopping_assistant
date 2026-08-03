/**
 * 传输层。Mock 与真实实现的唯一分叉点。
 *
 * F2 只提供 Mock 分支；F3 在此补真实 fetch、鉴权头装配和错误码分支，
 * 上层（sse.ts、api/chat.ts、Store）一行都不用改。
 *
 * Mock 走动态 import 且由环境变量守卫，生产构建不包含 fixture 镜像。
 */
export interface TransportRequest {
  path: string
  method: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  accept?: string
}

export type ChatTransport = (req: TransportRequest, signal: AbortSignal) => Promise<Response>

let override: ChatTransport | undefined
let cached: ChatTransport | undefined

/** 测试注入用。传 undefined 恢复默认解析。 */
export function setChatTransport(transport: ChatTransport | undefined): void {
  override = transport
  cached = undefined
}

export function isMockEnabled(): boolean {
  return import.meta.env.VITE_USE_MOCK === 'true'
}

export async function resolveTransport(): Promise<ChatTransport> {
  if (override) return override
  if (cached) return cached

  if (!isMockEnabled()) {
    throw new Error(
      '真实传输层将在 F3 提供。当前请设置 VITE_USE_MOCK=true 使用演示数据。',
    )
  }

  const { createMockTransport } = await import('./mock/transport')
  cached = createMockTransport()
  return cached
}
