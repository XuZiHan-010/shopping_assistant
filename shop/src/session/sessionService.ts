/**
 * 会话生命周期：创建访客、原地绑定演示顾客、换身份。
 *
 * 换身份必须先 `DELETE /sessions/current` 再新建（D7⑥）：已绑定顾客的购物车不得切换归属，
 * 所以不存在「就地改绑另一个身份」。
 */
import { clearSession, getSession, setSession } from '@/api/credentials'
import { bindDemoCustomerSession, createGuestSession, revokeSession } from '@/api/sessionApi'
import type { BindResult, ShopSession } from '@/types/session'

let latestCreation = 0

async function createGuest(shopSlug: string): Promise<ShopSession> {
  const creation = ++latestCreation
  const session = await createGuestSession(shopSlug)
  if (creation === latestCreation) setSession(session)
  return session
}

let opening: { shopSlug: string; promise: Promise<ShopSession> } | null = null

/** 进入店铺：同一店铺已有会话则复用；并发进入（如严格模式重复挂载）合并成一次创建。 */
export async function openShopSession(shopSlug: string): Promise<ShopSession> {
  const existing = getSession()
  if (existing && existing.shopSlug === shopSlug) {
    if (opening && opening.shopSlug !== shopSlug) {
      ++latestCreation
      opening = null
    }
    return existing
  }
  if (opening?.shopSlug === shopSlug) return opening.promise

  const promise = createGuest(shopSlug).finally(() => {
    if (opening?.promise === promise) opening = null
  })
  opening = { shopSlug, promise }
  return promise
}

export async function bindDemoCustomer(): Promise<BindResult> {
  const session = getSession()
  if (!session) throw new Error('没有可绑定的会话')
  const { cartAdjusted, expiresAt } = await bindDemoCustomerSession(session.sessionId)
  // 原地绑定：会话凭证不变，只把身份标记为已绑定。
  setSession({ ...session, isBound: true, expiresAt })
  return { cartAdjusted }
}

/** 注销当前会话并新建访客会话。注销失败（如已过期）也不阻断：本地凭证总是被清掉。 */
export async function switchDemoIdentity(shopSlug: string): Promise<ShopSession> {
  const session = getSession()
  if (session) {
    try {
      await revokeSession(session.sessionId)
    } catch {
      // 服务端会话已失效或不可达：本地清理照常进行。
    }
  }
  clearSession()
  return createGuest(shopSlug)
}
