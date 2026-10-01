/**
 * 公开的店铺与商品读取（无鉴权）。服务端组件会用到这里，所以**不得**依赖会话凭证模块——
 * 凭证是浏览器内存里的模块级状态，在服务端共享它会把不同访客的会话混在一起。
 */
import type { Coupon, Product, ProductDetail, StoreProfile } from '@/types/shop'
import { toCoupon, toProduct, toProductDetail, toStoreProfile } from './adapters/shop'
import { requestJson } from './client'
import type { components } from './generated'

type S = components['schemas']

const store = (slug: string) => `/api/v2/shop/stores/${encodeURIComponent(slug)}`

export async function getStore(slug: string, locale?: string): Promise<StoreProfile> {
  return toStoreProfile(await requestJson<S['StoreProfileResponse']>(
    store(slug), { headers: locale ? { 'Accept-Language': locale } : undefined },
  ))
}

export async function listProducts(slug: string, locale?: string): Promise<Product[]> {
  const page = await requestJson<S['CursorPage_ProductSummary_']>(
    `${store(slug)}/products?limit=100`, { headers: locale ? { 'Accept-Language': locale } : undefined },
  )
  return page.items.map(toProduct)
}

export async function getProduct(slug: string, productId: string, locale?: string): Promise<ProductDetail> {
  return toProductDetail(
    await requestJson<S['ProductDetailResponse']>(
      `${store(slug)}/products/${encodeURIComponent(productId)}`,
      { headers: locale ? { 'Accept-Language': locale } : undefined },
    ),
  )
}

export async function listCoupons(slug: string, locale?: string): Promise<Coupon[]> {
  const page = await requestJson<S['CursorPage_CouponSummary_']>(
    `${store(slug)}/coupons?limit=100`, { headers: locale ? { 'Accept-Language': locale } : undefined },
  )
  return page.items.map(toCoupon)
}


export async function listPopularProducts(slug: string, locale?: string): Promise<Product[]> {
  const page = await requestJson<S['CursorPage_ProductSummary_']>(
    `${store(slug)}/products?sort=popular&limit=8`,
    { headers: locale ? { 'Accept-Language': locale } : undefined },
  )
  return page.items.map(toProduct)
}
