/**
 * 凭证注册表：给 transport 层提供 `Authorization` / `X-Admin-Token` 请求头。
 *
 * 本文件**不 import 任何 `src/stores/**`**——`src/api/**` 依赖 `src/stores/**`
 * 会形成 store → api → store 的循环依赖（store 本身要调 api 发请求）。方向必须
 * 反过来：store 在启动时把「怎么拿 token」这个函数注册进来（`setCredentialProvider`），
 * `api` 只管在需要时调用它，从不知道 token 从哪来、由谁持有。
 *
 * Token 只进内存与请求头，不写 localStorage、URL、日志或构建产物：本文件里的
 * `CredentialSet` 只在 provider 调用的那一刻短暂存在于变量里，从不被本模块缓存
 * 或落盘。
 */
import { AppError } from './errors'

/** 请求要携带的凭证种类。`'none'` 用于不需要鉴权的公开接口（如演示商家列表）。 */
export type AuthScope = 'merchant' | 'admin' | 'none'

export interface CredentialSet {
  merchantToken?: string
  adminToken?: string
}

export type CredentialProvider = () => CredentialSet

let provider: CredentialProvider | undefined

/**
 * 注册凭证来源。由 `main.ts` 在应用启动时接入 Pinia store；测试可以直接调用，
 * 传 `undefined` 清空注册（用于测试间互相隔离，避免上一条用例的 provider 泄漏
 * 到下一条）。
 */
export function setCredentialProvider(fn: CredentialProvider | undefined): void {
  provider = fn
}

const SCOPE_LABEL: Record<Exclude<AuthScope, 'none'>, string> = {
  merchant: '商家登录',
  admin: '管理员登录',
}

/**
 * 按请求所需的鉴权范围组装请求头。
 *
 * 缺凭证时直接抛 `AppError('AUTH_REQUIRED', …)`，不发出注定会被后端拒绝的
 * 401 请求——省一次网络往返，也不给后端留下无意义的失败日志。
 *
 * `merchant` 与 `admin` 互不掺杂：管理员令牌绝不会出现在商家接口的请求头里，
 * 反之亦然。这是 F8（管理后台）能安全复用同一套 transport 的前提。
 */
export function buildAuthHeaders(scope: AuthScope): Record<string, string> {
  if (scope === 'none') return {}

  const credentials = provider?.() ?? {}

  if (scope === 'merchant') {
    if (!credentials.merchantToken) {
      throw new AppError('AUTH_REQUIRED', `缺少${SCOPE_LABEL.merchant}凭证，请重新选择商家。`)
    }
    return { Authorization: `Bearer ${credentials.merchantToken}` }
  }

  if (!credentials.adminToken) {
    throw new AppError('AUTH_REQUIRED', `缺少${SCOPE_LABEL.admin}凭证，请重新登录管理后台。`)
  }
  return { 'X-Admin-Token': credentials.adminToken }
}
