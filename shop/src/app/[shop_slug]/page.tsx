import { getStore, listCoupons, listPopularProducts } from '@/api/catalogApi'
import { serverLocale } from '@/i18n/serverLocale'
import { HomeView } from '@/views/HomeView'
import { orNotFound } from './serverData'

// 店铺和商品是公开数据；服务端首屏拉取热门八件，全部商品仅在用户展开时读取。
export const dynamic = 'force-dynamic'

export default async function StorePage({ params }: { params: Promise<{ shop_slug: string }> }) {
  const { shop_slug: shopSlug } = await params
  const locale = await serverLocale()
  const [store, popular, coupons] = await orNotFound(() => Promise.all([
    getStore(shopSlug, locale), listPopularProducts(shopSlug, locale), listCoupons(shopSlug, locale),
  ]))
  return <HomeView popular={popular} store={store} coupons={coupons} locale={locale} />
}
