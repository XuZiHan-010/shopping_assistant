import { ref } from 'vue'
import { defineStore } from 'pinia'

import { getChatBiCategories, getChatBiOverview, type ChatBiWindow } from '@/api/analytics'
import { AppError } from '@/api/errors'
import type { ChatBiCategoryRow, ChatBiOverview } from '@/types/analytics'

function dateString(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function windowFor(days: number): ChatBiWindow {
  const end = new Date()
  end.setHours(0, 0, 0, 0)
  const start = new Date(end)
  start.setDate(start.getDate() - days + 1)
  return { startDate: dateString(start), endDate: dateString(end) }
}

export const useAnalyticsStore = defineStore('analytics', () => {
  const adminToken = ref('')
  const overview = ref<ChatBiOverview>()
  const categories = ref<ChatBiCategoryRow[]>([])
  const loading = ref(false)
  const errorMessage = ref('')
  const windowDays = ref(7)
  const window = ref<ChatBiWindow>(windowFor(windowDays.value))

  function setAdminToken(token: string): void {
    adminToken.value = token.trim()
    errorMessage.value = ''
  }

  function setWindowDays(days: 7 | 30 | 90): void {
    windowDays.value = days
    window.value = windowFor(days)
    overview.value = undefined
    categories.value = []
    errorMessage.value = ''
  }

  async function load(): Promise<void> {
    if (!adminToken.value) throw new AppError('AUTH_REQUIRED', '未授权，请先输入管理员令牌。')

    loading.value = true
    errorMessage.value = ''
    try {
      const controller = new AbortController()
      const [nextOverview, nextCategories] = await Promise.all([
        getChatBiOverview(window.value, controller.signal),
        getChatBiCategories(window.value, controller.signal),
      ])
      overview.value = nextOverview
      categories.value = nextCategories
    } catch (error) {
      overview.value = undefined
      categories.value = []
      errorMessage.value = error instanceof Error ? error.message : 'Chat BI 数据加载失败。'
      throw error
    } finally {
      loading.value = false
    }
  }

  function signOut(): void {
    adminToken.value = ''
    overview.value = undefined
    categories.value = []
    errorMessage.value = ''
  }

  return {
    adminToken,
    overview,
    categories,
    loading,
    errorMessage,
    windowDays,
    window,
    setAdminToken,
    setWindowDays,
    load,
    signOut,
  }
})
