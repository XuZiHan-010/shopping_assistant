import { ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { getChatBiCategories, getChatBiOverview, type ChatBiWindow } from '@/api/analytics'
import { AppError } from '@/api/errors'
import type { ChatBiCategoryRow, ChatBiOverview } from '@/types/analytics'

import { useLocaleStore } from './locale'

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

  /**
   * 语言切换时重新拉一次总览与分类——`category_display_name` 按
   * Accept-Language 分流（`backend/app/api/routes/analytics.py::_display_name`）。
   * 未登录或从未成功加载过时直接跳过：登录前不该抢在管理员输入令牌之前
   * 发请求（会稳定命中 401），也不该把"从未打开过看板"误判成"需要刷新"。
   */
  async function reloadForLocale(): Promise<void> {
    if (!adminToken.value || !overview.value) return
    try {
      await load()
    } catch {
      // load() 失败时会自己把 overview/categories 清空并写 errorMessage——
      // 这里只是不让语言切换触发的这次刷新失败以未处理拒绝的形式冒出去。
    }
  }

  const localeStore = useLocaleStore()
  watch(
    () => localeStore.locale,
    () => {
      void reloadForLocale()
    },
  )

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
    reloadForLocale,
  }
})
