import { getProduct } from '@/api/catalogApi'
import { serverLocale } from '@/i18n/serverLocale'
import { ProductDetailBody } from '@/views/ProductDetailBody'
import { orNotFound } from '../../serverData'

export const dynamic = 'force-dynamic'

export default async function ProductPage({
  params,
}: {
  params: Promise<{ shop_slug: string; product_id: string }>
}) {
  const { shop_slug: shopSlug, product_id: productId } = await params
  const locale = await serverLocale()
  const product = await orNotFound(() => getProduct(shopSlug, productId, locale))
  return <ProductDetailBody product={product} shopSlug={shopSlug} />
}
