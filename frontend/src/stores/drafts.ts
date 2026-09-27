import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  discardDraft as discardDraftRequest,
  fetchDrafts,
  type DraftKind,
  type DraftState,
  type DraftSummary,
} from '@/api/adapters/merchantOps'

import { registerSessionScopedReset, useAuthStore } from './auth'

export interface LoadDraftsOptions {
  cursor?: string | null
  limit?: number
  state?: DraftState
  kind?: DraftKind
  batchId?: string
}

/**
 * 一组共享同一个 `batchId` 的子草稿（批量商品内容起草，Task 3）；
 * `batchId` 为 `null` 表示单独一份、不属于任何批次的草稿——每份单独成组，
 * 与批量草稿走同一套分组展示，界面不需要区分两种形态。
 */
export interface DraftGroup {
  batchId: string | null
  items: DraftSummary[]
}

/**
 * 草稿列表 Store（`n2-merchant-vue-v2-migration` Task 4）。**只管列表**，
 * 不持有任何一份草稿详情或审批证据——详情与证据只活在 `ApprovalView` 的组件
 * 内存里（契约 §8.7.9：证据只供工作台 Adapter 消费，不进入会被 devtools/
 * 持久化插件看到的 Pinia Store）。批准成功后由 `ApprovalView` 调用
 * `markApplied` 把返回的新摘要合并进列表，不需要为此重新拉一整页。
 */
export const useDraftsStore = defineStore('drafts', () => {
  const items = ref<DraftSummary[]>([])
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

  async function loadDrafts(options: LoadDraftsOptions = {}): Promise<void> {
    const auth = useAuthStore()
    loading.value = true
    errorMessage.value = ''
    try {
      const page = await auth.callWithSessionRetry((sid) => fetchDrafts(sid, options))
      items.value = options.cursor ? [...items.value, ...page.items] : page.items
      nextCursor.value = page.nextCursor
      hasMore.value = page.hasMore
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '草稿列表加载失败。'
      throw error
    } finally {
      loading.value = false
    }
  }

  async function discardDraft(draftId: string): Promise<void> {
    const auth = useAuthStore()
    await auth.callWithSessionRetry((sid) => discardDraftRequest(sid, draftId))
    items.value = items.value.filter((item) => item.id !== draftId)
  }

  /** `ApprovalView` 批准成功后调用；证据不经过本 Store，只合并草稿摘要。 */
  function markApplied(summary: DraftSummary): void {
    items.value = items.value.map((item) => (item.id === summary.id ? summary : item))
  }

  /**
   * 按 `batchId` 分组，保持 `items` 里各条目原有的相对顺序——无批次的草稿
   * 各自独立成一组，不与其他无批次草稿合并（它们互不相关，合并会让界面
   * 误以为它们是同一批）。
   */
  const groupedItems = computed<DraftGroup[]>(() => {
    const groups: DraftGroup[] = []
    const indexByBatchId = new Map<string, number>()
    for (const item of items.value) {
      if (item.batchId === null) {
        groups.push({ batchId: null, items: [item] })
        continue
      }
      const existingIndex = indexByBatchId.get(item.batchId)
      if (existingIndex === undefined) {
        indexByBatchId.set(item.batchId, groups.length)
        groups.push({ batchId: item.batchId, items: [item] })
      } else {
        groups[existingIndex]!.items.push(item)
      }
    }
    return groups
  })

  return {
    items,
    nextCursor,
    hasMore,
    loading,
    errorMessage,
    groupedItems,
    loadDrafts,
    discardDraft,
    markApplied,
  }
})
