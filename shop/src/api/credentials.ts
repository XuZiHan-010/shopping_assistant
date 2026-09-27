/**
 * 顾客会话凭证：**只存浏览器内存**（PRD C3，2026-09-21 用户裁定）。
 *
 * 不写 localStorage / sessionStorage / cookie / URL。刷新页面即丢失，靠重新创建访客会话
 * （未绑定则原购物车暂时无法访问）或重新绑定同一演示身份（恢复购物车）来接续。
 * 这里的模块级变量就是唯一存放处；测试之外没有第二条读写路径。
 */
import { useSyncExternalStore } from 'react'
import type { ShopSession } from '@/types/session'

let current: ShopSession | null = null
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

export function getSession(): ShopSession | null {
  return current
}

export function setSession(session: ShopSession | null): void {
  current = session
  emit()
}

export function clearSession(): void {
  setSession(null)
}

export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useSession(): ShopSession | null {
  return useSyncExternalStore(subscribeSession, getSession, () => null)
}

export function resetSessionForTest(): void {
  setSession(null)
}
