import { ref } from 'vue'
import { defineStore } from 'pinia'

import {
  fetchMerchantCoupons,
  fetchMerchantProductContent,
  type MerchantCoupon,
  type MerchantProductContent,
} from '@/api/adapters/merchantOps'

import { registerSessionScopedReset, useAuthStore } from './auth'

export const useCatalogOpsStore = defineStore('catalogOps', () => {
  const products = ref<MerchantProductContent[]>([])
  const coupons = ref<MerchantCoupon[]>([])
  const nextProductCursor = ref<string | null>(null)
  const nextCouponCursor = ref<string | null>(null)
  const hasMoreProducts = ref(false)
  const hasMoreCoupons = ref(false)
  const loading = ref(false)
  const errorMessage = ref('')

  registerSessionScopedReset(() => {
    products.value = []
    coupons.value = []
    nextProductCursor.value = null
    nextCouponCursor.value = null
    hasMoreProducts.value = false
    hasMoreCoupons.value = false
    errorMessage.value = ''
  })

  async function load(): Promise<void> {
    const auth = useAuthStore()
    loading.value = true
    errorMessage.value = ''
    try {
      const [productPage, couponPage] = await Promise.all([
        auth.callWithSessionRetry((sid) => fetchMerchantProductContent(sid, { limit: 20 })),
        auth.callWithSessionRetry((sid) => fetchMerchantCoupons(sid, { limit: 20 })),
      ])
      products.value = productPage.items
      coupons.value = couponPage.items
      nextProductCursor.value = productPage.nextCursor
      nextCouponCursor.value = couponPage.nextCursor
      hasMoreProducts.value = productPage.hasMore
      hasMoreCoupons.value = couponPage.hasMore
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '商品与优惠券加载失败。'
      throw error
    } finally {
      loading.value = false
    }
  }

  async function loadMoreProducts(): Promise<void> {
    if (!nextProductCursor.value) return
    const auth = useAuthStore()
    loading.value = true
    try {
      const page = await auth.callWithSessionRetry((sid) =>
        fetchMerchantProductContent(sid, { cursor: nextProductCursor.value, limit: 20 }),
      )
      products.value = [...products.value, ...page.items]
      nextProductCursor.value = page.nextCursor
      hasMoreProducts.value = page.hasMore
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '商品加载失败。'
      throw error
    } finally {
      loading.value = false
    }
  }

  async function loadMoreCoupons(): Promise<void> {
    if (!nextCouponCursor.value) return
    const auth = useAuthStore()
    loading.value = true
    try {
      const page = await auth.callWithSessionRetry((sid) =>
        fetchMerchantCoupons(sid, { cursor: nextCouponCursor.value, limit: 20 }),
      )
      coupons.value = [...coupons.value, ...page.items]
      nextCouponCursor.value = page.nextCursor
      hasMoreCoupons.value = page.hasMore
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '优惠券加载失败。'
      throw error
    } finally {
      loading.value = false
    }
  }

  return {
    products, coupons, nextProductCursor, nextCouponCursor,
    hasMoreProducts, hasMoreCoupons, loading, errorMessage,
    load, loadMoreProducts, loadMoreCoupons,
  }
})
