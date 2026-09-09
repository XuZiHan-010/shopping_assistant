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

  /**
   * 每次语言切换递增一次。写状态之前先比较请求发出时快照的 epoch 与当前
   * epoch——不一致说明这个响应对应的是已经被切走的语言，直接丢弃，不写入
   * Store（与 `stores/chat.ts` 同一套机制，Task 11 Step 6 的原子刷新/防
   * 竞态防护——之前只在 chat.ts 落地，本次补齐到 analytics.ts）。
   */
  const localeEpoch = ref(0)

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

    const epochAtRequest = localeEpoch.value
    loading.value = true
    errorMessage.value = ''
    try {
      const controller = new AbortController()
      const [nextOverview, nextCategories] = await Promise.all([
        getChatBiOverview(window.value, controller.signal),
        getChatBiCategories(window.value, controller.signal),
      ])
      // 语言切换后这次响应已经过期：交给更晚那次 reloadForLocale 发起的
      // 请求收尾，不能用旧语言的数据覆盖已经写入的新语言数据。
      if (epochAtRequest !== localeEpoch.value) return
      overview.value = nextOverview
      categories.value = nextCategories
    } catch (error) {
      if (epochAtRequest !== localeEpoch.value) return
      overview.value = undefined
      categories.value = []
      errorMessage.value = error instanceof Error ? error.message : 'Chat BI 数据加载失败。'
      throw error
    } finally {
      // 同理：过期请求的收尾不能把 loading 复位成 false，那可能会把更晚
      // 那次仍在途的请求的加载态提前关掉。
      if (epochAtRequest === localeEpoch.value) loading.value = false
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
    // 无条件先递增：即使这次调用本身是 no-op（未登录/从未加载过），也要让
    // 任何仍在途的旧 epoch 请求（例如手动点「刷新」触发的 load()）在响应
    // 回来时被判定为过期而丢弃。
    localeEpoch.value += 1
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
