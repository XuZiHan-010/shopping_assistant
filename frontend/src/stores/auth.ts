import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { listDemoMerchants, type DemoMerchantView } from '@/api/chat'

import { useLocaleStore } from './locale'

/**
 * 只持久化非敏感的商家标识。Token 仅进内存与请求头，
 * 不写 localStorage、URL、日志或构建产物（前端方案 §6.2）。
 */
export const MERCHANT_STORAGE_KEY = 'selected_demo_merchant_key'

export const useAuthStore = defineStore('auth', () => {
  const merchants = ref<DemoMerchantView[]>([])
  const selected = ref<DemoMerchantView | undefined>(undefined)
  const restoreNotice = ref('')

  /**
   * 每次语言切换递增一次。写状态之前先比较请求发出时快照的 epoch 与当前
   * epoch——不一致说明这个响应对应的是已经被切走的语言，直接丢弃，不写入
   * Store（与 `stores/chat.ts` 同一套机制，Task 11 Step 6 的原子刷新/防
   * 竞态防护——之前只在 chat.ts 落地，本次补齐到 auth.ts）。
   */
  const localeEpoch = ref(0)

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

  /**
   * 演示 Token 在服务端失效时调用（后端返回 401 `AUTH_REQUIRED`）——见
   * `AssistantView` 对 `chatStore.messages` 里 `AUTH_REQUIRED` 错误的监听。
   *
   * 清掉内存里的 Token 与落盘的商家标识，但**保留 `merchants` 列表**：那是公开
   * 数据，重新拉一次没有必要，也会让切换器重新弹出时多等一次网络往返。
   * `selected` 本身不清空——切换器还要接着显示「当前商家是谁」，只是它已经
   * 没有可用凭证了；`credentials.ts` 的 `buildAuthHeaders` 会在下一次请求时
   * 因为 `merchantToken` 缺失而直接拒绝，不会带着空 Token 发出注定失败的请求。
   */
  function invalidate(): void {
    if (selected.value) selected.value = { ...selected.value, token: undefined }
    sessionStorage.removeItem(MERCHANT_STORAGE_KEY)
    restoreNotice.value = '演示身份已失效，请重新选择商家。'
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

  /**
   * 语言切换时重新拉一次商家列表——`/api/demo/merchants` 的 `display_name`
   * 按 Accept-Language 分流（`backend/app/api/routes/demo.py::_display_name`），
   * 不重新拉的话切换语言后切换器还会显示上一语言的商家名。
   *
   * 只重新指向"同一个商家"的新展示名，`token` 原样保留（`merchantId` 不变
   * 则 Token 也不变——演示 Token 不随语言轮换）；`invalidate()` 清空过的
   * Token 不会因为这次刷新被悄悄复活，一次单纯的语言切换不应该有"重新登录"
   * 的副作用。未曾加载过商家列表（`merchants.value` 为空）时直接跳过——
   * 那是尚未完成初始 `restore()` 的情况，不该抢在它前面发请求。
   */
  async function reloadForLocale(): Promise<void> {
    // 无条件先递增：即使这次调用本身是 no-op（尚未加载过商家列表），也要让
    // 任何仍在途的旧 epoch 请求在响应回来时被判定为过期而丢弃。
    localeEpoch.value += 1
    if (merchants.value.length === 0) return

    const epochAtRequest = localeEpoch.value
    const previousMerchantId = selected.value?.merchantId
    const previousToken = selected.value?.token

    let nextMerchants: DemoMerchantView[]
    try {
      nextMerchants = await listDemoMerchants(new AbortController().signal)
    } catch {
      // 静默失败：保留当前（可能是上一语言）的商家列表和选中项，不能让一次
      // 语言切换的刷新失败打断用户正在做的事。
      return
    }

    // 响应回来之前又发生了一次语言切换：这次响应对应的是已经过期的语言，
    // 丢弃，交给更晚那次 reloadForLocale 的请求收尾——否则先发后至的旧语言
    // 响应可能覆盖掉后发先至的新语言响应已经写入的数据。
    if (epochAtRequest !== localeEpoch.value) return

    merchants.value = nextMerchants

    if (!previousMerchantId) return
    const fresh = merchants.value.find((item) => item.merchantId === previousMerchantId)
    if (!fresh) return
    selected.value = previousToken === undefined ? { ...fresh, token: undefined } : fresh
  }

  const localeStore = useLocaleStore()
  watch(
    () => localeStore.locale,
    () => {
      void reloadForLocale()
    },
  )

  return {
    merchants,
    selected,
    displayNames,
    restoreNotice,
    loadMerchants,
    selectByDisplayName,
    restore,
    invalidate,
    reloadForLocale,
  }
})
