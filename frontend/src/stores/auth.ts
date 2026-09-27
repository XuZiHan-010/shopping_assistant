import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { createMerchantSession, revokeMerchantSession } from '@/api/adapters/session'
import { listDemoMerchants, type DemoMerchantView } from '@/api/chat'
import { AppError } from '@/api/errors'

import { useLocaleStore } from './locale'

/**
 * v2 会话态 Store（草稿、库存、当日简报……）在创建时调用它注册自己的清空函数。
 * 切换商家会话（`selectAndOpenSession`）统一遍历调用——新增一个会话态 Store 时
 * 只需要在那个 Store 自己的文件里注册一行，不用回来改 `auth.ts`。
 * 返回值是注销函数，供测试或热更新场景反注册，正常运行时不需要调用。
 */
const sessionScopedResetHandlers = new Set<() => void>()

export function registerSessionScopedReset(fn: () => void): () => void {
  sessionScopedResetHandlers.add(fn)
  return () => sessionScopedResetHandlers.delete(fn)
}

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

  /**
   * v2 商家会话 ID。**只存内存**，刷新页面即丢失（`n2-merchant-vue-v2-migration` Task 2）——
   * 与 v1 的 `merchantToken` 同一纪律，不写 `sessionStorage` / `localStorage`。
   */
  const sessionId = ref<string | null>(null)

  const displayNames = computed(() => merchants.value.map((item) => item.displayName))

  /**
   * 每次丢弃会话递增。换取会话是异步的：请求发出后商家若被切走，回来的那枚
   * 会话属于旧商家，比较 epoch 就能认出来并丢弃，不会把 A 的会话装在 B 名下。
   */
  let sessionEpoch = 0
  let pendingSession: Promise<string> | null = null

  /**
   * 同步丢弃当前 v2 会话：内存 ID 立即清空、会话态 Store 立即清空，旧会话在后台
   * 尽力注销。同步清空是「绝不在同一个 `X-Session-Id` 下改商家」的保证——
   * 调用方返回的那一刻旧 ID 已不可用，不依赖注销请求是否成功。
   */
  function dropSession(): void {
    sessionEpoch += 1
    pendingSession = null
    const previous = sessionId.value
    sessionId.value = null
    for (const reset of sessionScopedResetHandlers) reset()
    // 注销失败不阻塞：旧会话本就按服务端 TTL 过期，为一次可能是网络抖动的
    // 注销失败卡住「切换商家」，代价比留一个反正很快过期的旧会话更大。
    if (previous) void revokeMerchantSession(previous).catch(() => undefined)
  }

  /** 用商家的演示 Bearer Token 换取一个新的 v2 会话，写入内存并选中该商家。 */
  async function openSession(merchant: DemoMerchantView): Promise<void> {
    if (!merchant.token) {
      throw new AppError('AUTH_REQUIRED', '缺少商家登录凭证，请重新选择商家。')
    }
    const epochAtRequest = sessionEpoch
    const session = await createMerchantSession(merchant.token)
    if (epochAtRequest !== sessionEpoch) {
      void revokeMerchantSession(session.sessionId).catch(() => undefined)
      throw new AppError('AUTH_REQUIRED', '商家已切换，请重新操作。')
    }
    sessionId.value = session.sessionId
    selected.value = merchant
  }

  /**
   * 拿到当前商家可用的会话 ID；没有就按需换取。直接打开 v2 页面或刷新之后，
   * 商家列表可能都还没加载——先按 `restore()` 的既有规则选回商家，再换取会话
   * （计划 Task 2「刷新恢复」）。并发调用共用同一次换取。
   */
  async function ensureSession(): Promise<string> {
    if (sessionId.value) return sessionId.value
    if (!pendingSession) {
      const pending = (async () => {
        if (!selected.value) await restore()
        const merchant = selected.value
        if (!merchant?.token) {
          throw new AppError('AUTH_REQUIRED', '会话尚未建立，请先选择商家。')
        }
        await openSession(merchant)
        return sessionId.value as string
      })()
      pendingSession = pending
      void pending
        .finally(() => {
          if (pendingSession === pending) pendingSession = null
        })
        .catch(() => undefined)
    }
    return pendingSession
  }

  /** 显式切换到某个商家并立即换取它的会话。 */
  async function selectAndOpenSession(merchant: DemoMerchantView): Promise<void> {
    select(merchant)
    await ensureSession()
  }

  /**
   * 包一层「遇到 `SESSION_INVALID` 就换新会话重试一次」的语义，供草稿、库存等
   * 会话态 Store 的读写调用复用，不用各自实现同一套恢复逻辑。重试后仍然失败
   * 就原样把错误抛给调用方——是否弹出商家切换器、如何保留用户未发送的输入，
   * 是界面层的职责，不属于本方法。
   */
  async function callWithSessionRetry<T>(call: (sid: string) => Promise<T>): Promise<T> {
    const sid = await ensureSession()
    try {
      return await call(sid)
    } catch (error) {
      if (error instanceof AppError && error.code === 'SESSION_INVALID') {
        // 只清掉失效的那一枚；若并发的另一次调用已经换上了新会话，就直接复用。
        if (sessionId.value === sid) sessionId.value = null
        return await call(await ensureSession())
      }
      throw error
    }
  }

  async function loadMerchants(): Promise<void> {
    merchants.value = await listDemoMerchants(new AbortController().signal)
    if (!selected.value) selected.value = merchants.value[0]
  }

  /**
   * 所有「改选商家」都走这里（切换器、刷新恢复、显式切换）。换成另一个商家时
   * 先丢弃旧会话——否则 v1 切换器改了商家，v2 页面仍拿旧商家的会话取数。
   */
  function select(merchant: DemoMerchantView): void {
    if (selected.value?.merchantId !== merchant.merchantId) dropSession()
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
    dropSession()
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
    sessionId,
    openSession,
    selectAndOpenSession,
    callWithSessionRetry,
  }
})
