import { OrdersView } from '@/views/OrdersView'

export default async function OrdersPage({ params }: { params: Promise<{ shop_slug: string }> }) {
  const { shop_slug: shopSlug } = await params
  return <OrdersView shopSlug={shopSlug} />
}
