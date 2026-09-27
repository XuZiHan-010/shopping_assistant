import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchAfterSaleDetail, fetchAfterSales } from '@/api/adapters/afterSales'
import type { AfterSaleState, MerchantAfterSale, MerchantAfterSaleDetail } from '@/types/afterSales'
import { registerSessionScopedReset, useAuthStore } from './auth'

export const useAfterSalesStore = defineStore('afterSales', () => {
  const items = ref<MerchantAfterSale[]>([])
  const detail = ref<MerchantAfterSaleDetail | null>(null)
  const nextCursor = ref<string | null>(null)
  const loading = ref(false)
  const errorMessage = ref('')
  const stateFilter = ref<AfterSaleState | ''>('')

  registerSessionScopedReset(() => {
    items.value = []
    detail.value = null
    nextCursor.value = null
    errorMessage.value = ''
  })

  async function load(cursor?: string): Promise<void> {
    loading.value = true
    errorMessage.value = ''
    try {
      const auth = useAuthStore()
      const page = await auth.callWithSessionRetry((sid) => fetchAfterSales(sid, {
        state: stateFilter.value || undefined, cursor, limit: 20,
      }))
      items.value = cursor ? [...items.value, ...page.items] : page.items
      nextCursor.value = page.nextCursor
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '售后队列加载失败'
    } finally {
      loading.value = false
    }
  }

  async function open(id: string): Promise<void> {
    loading.value = true
    errorMessage.value = ''
    try {
      const auth = useAuthStore()
      detail.value = await auth.callWithSessionRetry((sid) => fetchAfterSaleDetail(sid, id))
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '售后详情加载失败'
    } finally {
      loading.value = false
    }
  }

  return { items, detail, nextCursor, loading, errorMessage, stateFilter, load, open }
})
