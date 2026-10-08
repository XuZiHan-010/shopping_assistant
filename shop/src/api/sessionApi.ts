/** 会话相关端点的线上调用；返回领域模型，wire 类型不出 api/ 层。 */
import type { BindResult, ShopSession } from '@/types/session'
import { toBindResult, toGuestSession } from './adapters/session'
import { requestJson } from './client'
import type { components } from './generated'

type Created = components['schemas']['ShopSessionCreateResponse']
type Bound = components['schemas']['DemoCustomerBindResponse']

export async function createGuestSession(shopSlug: string): Promise<ShopSession> {
  const raw = await requestJson<Created>('/api/v2/shop/sessions', {
    method: 'POST',
    body: { shop_slug: shopSlug },
  })
  return toGuestSession(raw, shopSlug)
}

export async function bindDemoCustomerSession(
  sessionId: string,
): Promise<BindResult & { expiresAt: string }> {
  const raw = await requestJson<Bound>('/api/v2/shop/sessions/demo-customer', {
    method: 'POST',
    body: {},
    sessionId,
  })
  return toBindResult(raw)
}

export async function revokeSession(sessionId: string): Promise<void> {
  await requestJson<void>('/api/v2/shop/sessions/current', { method: 'DELETE', sessionId })
}
