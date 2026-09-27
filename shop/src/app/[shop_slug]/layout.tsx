import type { ReactNode } from 'react'
import { ShopShell } from '@/session/ShopShell'

export default async function ShopLayout({
  children,
  params,
}: {
  children: ReactNode
  params: Promise<{ shop_slug: string }>
}) {
  const { shop_slug: shopSlug } = await params
  return <ShopShell shopSlug={shopSlug}>{children}</ShopShell>
}
