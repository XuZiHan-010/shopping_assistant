/**
 * 游标分页列表的共用状态机（W Task 9 fix round 1：订单页、商品页）。
 *
 * 契约 §8.7.4：签名游标绑定端点、主体、筛选条件、语言与 limit，且 24 小时过期。
 * 这里统一三条规则，避免各页手写后逐渐走样：
 *
 * 1. `reload()` 总是从第一页（`cursor = null`）读起，并递增请求令牌；
 * 2. `loadMore()` 沿用发起时的令牌，令牌变了（期间有 `reload()`，或所在作用域已销毁）
 *    就丢弃结果——晚到的旧页不会写进新列表；
 * 3. `loadMore()` 得到 `INVALID_CURSOR` 时不重试旧游标，而是从第一页重读（§8.7.4 第 5 条），
 *    并置 `restarted = true`，让页面礼貌地告诉用户列表被重新加载了；用户下一次主动
 *    `reload()`（换筛选、重试）时清除该标记。
 *
 * `fetchPage` 在调用时同步读取当下的筛选条件，调用方不必另行快照。
 */
import { computed, getCurrentScope, onScopeDispose, ref, shallowRef, type Ref } from 'vue'

import { AppError } from '@/api/errors'

export interface CursorPage<T> {
  items: T[]
  nextCursor: string | null
  hasMore: boolean
}

export type CursorListStatus = 'loading' | 'ready' | 'error'
export type CursorMoreStatus = 'idle' | 'loading' | 'error'

export function useCursorList<T>(fetchPage: (cursor: string | null) => Promise<CursorPage<T>>) {
  const items = shallowRef<T[]>([]) as Ref<T[]>
  const status = ref<CursorListStatus>('loading')
  const moreStatus = ref<CursorMoreStatus>('idle')
  const nextCursor = ref<string | null>(null)
  const restarted = ref(false)
  const hasMore = computed(() => nextCursor.value !== null)

  let token = 0

  function applyPage(page: CursorPage<T>, append: boolean): void {
    items.value = append ? [...items.value, ...page.items] : page.items
    nextCursor.value = page.hasMore ? page.nextCursor : null
  }

  async function firstPage(isRestart: boolean): Promise<void> {
    const current = ++token
    restarted.value = isRestart
    status.value = 'loading'
    moreStatus.value = 'idle'
    items.value = []
    nextCursor.value = null
    try {
      const page = await fetchPage(null)
      if (current !== token) return
      applyPage(page, false)
      status.value = 'ready'
    } catch {
      if (current !== token) return
      status.value = 'error'
    }
  }

  /** 从第一页重读（换筛选、重试、首次加载）。 */
  function reload(): Promise<void> {
    return firstPage(false)
  }

  async function loadMore(): Promise<void> {
    const cursor = nextCursor.value
    if (cursor === null || moreStatus.value === 'loading') return
    const current = token
    moreStatus.value = 'loading'
    try {
      const page = await fetchPage(cursor)
      if (current !== token) return
      applyPage(page, true)
      moreStatus.value = 'idle'
    } catch (error) {
      if (current !== token) return
      if (error instanceof AppError && error.code === 'INVALID_CURSOR') {
        // 游标已不对应当前查询形状（语言、筛选或会话变了）或已过期：从第一页重读。
        await firstPage(true)
        return
      }
      moreStatus.value = 'error'
    }
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      token += 1
    })
  }

  return { items, status, moreStatus, hasMore, restarted, reload, loadMore }
}

/**
 * 焦点因所在节点被移除（重试按钮、「加载更多」按钮随状态切换消失）而掉到 body 时，
 * 交给 `target`（通常是带 `tabindex="-1"` 的列表面板）。焦点仍在别处时不抢。
 */
export function focusIfLost(target: HTMLElement | null): void {
  if (!target) return
  const active = document.activeElement
  if (!active || active === document.body || !active.isConnected) target.focus()
}
