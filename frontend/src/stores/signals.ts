import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchSignals, ignoreSignal } from '@/api/adapters/afterSales'
import type { CustomerSignal } from '@/types/afterSales'
import { registerSessionScopedReset, useAuthStore } from './auth'

export const useSignalsStore = defineStore('signals', () => {
  const items = ref<CustomerSignal[]>([])
  const includeIgnored = ref(false)
  const nextCursor = ref<string | null>(null)
  const loading = ref(false)
  const errorMessage = ref('')
  const pendingIgnore = new Map<string, { reason: string; clientRequestId: string }>()

  registerSessionScopedReset(() => {
    items.value = []
    nextCursor.value = null
    errorMessage.value = ''
    pendingIgnore.clear()
  })

  async function load(cursor?: string): Promise<void> {
    loading.value = true
    errorMessage.value = ''
    try {
      const auth = useAuthStore()
      const page = await auth.callWithSessionRetry((sid) => fetchSignals(sid, {
        includeIgnored: includeIgnored.value, cursor, limit: 20,
      }))
      items.value = cursor ? [...items.value, ...page.items] : page.items
      nextCursor.value = page.nextCursor
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '顾客信号加载失败'
    } finally {
      loading.value = false
    }
  }

  async function ignore(id: string, reason: string): Promise<void> {
    if (!reason.trim()) return
    const auth = useAuthStore()
    const key = pendingIgnore.get(id)
    const request = key?.reason === reason.trim() ? key : {
      reason: reason.trim(), clientRequestId: crypto.randomUUID(),
    }
    pendingIgnore.set(id, request)
    errorMessage.value = ''
    try {
      await auth.callWithSessionRetry((sid) =>
        ignoreSignal(sid, id, request.reason, request.clientRequestId),
      )
      pendingIgnore.delete(id)
      await load()
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '忽略信号失败，请重试'
      throw error
    }
  }

  return { items, includeIgnored, nextCursor, loading, errorMessage, load, ignore }
})
