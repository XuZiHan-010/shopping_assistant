import { OrderClient } from './OrderClient'

export default async function OrderPage({
  params,
}: {
  params: Promise<{ shop_slug: string; order_id: string }>
}) {
  const { order_id: orderId, shop_slug: shopSlug } = await params
  return <OrderClient orderId={orderId} shopSlug={shopSlug} />
}
