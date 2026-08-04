import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { listDemoMerchants, type DemoMerchantView } from '@/api/chat'

/**
 * 只持久化非敏感的商家标识。Token 仅进内存与请求头，
 * 不写 localStorage、URL、日志或构建产物（前端方案 §6.2）。
 */
export const MERCHANT_STORAGE_KEY = 'selected_demo_merchant_key'

export const useAuthStore = defineStore('auth', () => {
  const merchants = ref<DemoMerchantView[]>([])
  const selected = ref<DemoMerchantView | undefined>(undefined)
  const restoreNotice = ref('')

  const displayNames = computed(() => merchants.value.map((item) => item.displayName))

  async function loadMerchants(): Promise<void> {
    merchants.value = await listDemoMerchants(new AbortController().signal)
    if (!selected.value) selected.value = merchants.value[0]
  }

  function select(merchant: DemoMerchantView): void {
    selected.value = merchant
    sessionStorage.setItem(MERCHANT_STORAGE_KEY, merchant.merchantId)
  }

  function selectByDisplayName(displayName: string): void {
    const found = merchants.value.find((item) => item.displayName === displayName)
    if (found) select(found)
  }

  async function restore(): Promise<void> {
    try {
      await loadMerchants()
    } catch {
      // restore 由 onMounted 以 fire-and-forget 方式调用，让它把异常抛出去只会
      // 变成一条未处理的 Promise 拒绝：控制台一行红字，而界面上的切换器永远停在
      // 「加载中」，不给用户任何解释。转成用户看得见的提示，并让调用方不必 catch。
      restoreNotice.value = '演示商家列表加载失败，请刷新页面后重试。'
      return
    }

    const key = sessionStorage.getItem(MERCHANT_STORAGE_KEY)
    if (!key) return

    const found = merchants.value.find((item) => item.merchantId === key)
    if (found) {
      select(found)
      return
    }

    restoreNotice.value = '上次使用的演示商家已不可用，请重新选择商家。'
    if (merchants.value[0]) select(merchants.value[0])
  }

  return {
    merchants,
    selected,
    displayNames,
    restoreNotice,
    loadMerchants,
    selectByDisplayName,
    restore,
  }
})
