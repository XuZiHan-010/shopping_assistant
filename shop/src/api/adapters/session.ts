import type { BindResult, ShopSession } from '@/types/session'
import type { components } from '../generated'

type Created = components['schemas']['ShopSessionCreateResponse']
type Bound = components['schemas']['DemoCustomerBindResponse']

export function toGuestSession(raw: Created, shopSlug: string): ShopSession {
  return { sessionId: raw.session_id, shopSlug, isBound: false, expiresAt: raw.expires_at }
}

export function toBindResult(raw: Bound): BindResult & { expiresAt: string } {
  return { cartAdjusted: raw.cart_adjusted, expiresAt: raw.expires_at }
}
