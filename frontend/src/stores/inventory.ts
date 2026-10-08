import { ref } from 'vue'
import { defineStore } from 'pinia'

import {
  fetchInventoryAlerts,
  type InventoryAlert,
  type InventoryAlertKind,
} from '@/api/adapters/merchantOps'

import { registerSessionScopedReset, useAuthStore } from './auth'

export interface LoadAlertsOptions {
  cursor?: string | null
  limit?: number
  kind?: InventoryAlertKind
}

/** 库存告警 Store（`n2-merchant-vue-v2-migration` Task 5）。只读，本组没有任何写端点。 */
export const useInventoryStore = defineStore('inventory', () => {
  const items = ref<InventoryAlert[]>([])
  const nextCursor = ref<string | null>(null)
  const hasMore = ref(false)
  const loading = ref(false)
  const errorMessage = ref('')

  registerSessionScopedReset(() => {
    items.value = []
    nextCursor.value = null
    hasMore.value = false
    errorMessage.value = ''
  })

  async function loadAlerts(options: LoadAlertsOptions = {}): Promise<void> {
    const auth = useAuthStore()
    loading.value = true
    errorMessage.value = ''
    try {
      const page = await auth.callWithSessionRetry((sid) => fetchInventoryAlerts(sid, options))
      items.value = options.cursor ? [...items.value, ...page.items] : page.items
      nextCursor.value = page.nextCursor
      hasMore.value = page.hasMore
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '库存告警加载失败。'
      throw error
    } finally {
      loading.value = false
    }
  }

  return { items, nextCursor, hasMore, loading, errorMessage, loadAlerts }
})
