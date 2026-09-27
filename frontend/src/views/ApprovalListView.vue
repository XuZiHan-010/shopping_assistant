<script setup lang="ts">
/**
 * 草稿列表：按 `batchId` 分组展示，支持勾选批准（PRD M4，商家计划 Task 3、Task 8）。
 *
 * **审批证据只存本组件的临时局部变量，绝不写入 Pinia Store**——与 `ApprovalView`
 * 遵守同一条边界（契约 §8.7.9）。批准整批时对每个勾选的子草稿依次
 * `fetchDraftDetail`（签发新证据）→ `applyDraft`（消费证据），逐个应用而不是
 * 一次性批量请求：每份子草稿有自己的 `draftVersion`/`targetVersion`，审批闸门
 * 按草稿逐个校验，批量端点会破坏"一份草稿一个版本"的状态机（Task 3 设计说明）。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { applyDraft, fetchDraftDetail } from '@/api/adapters/merchantOps'
import { useAuthStore } from '@/stores/auth'
import { useDraftsStore, type DraftGroup } from '@/stores/drafts'

const auth = useAuthStore()
const draftsStore = useDraftsStore()
const { t } = useI18n()

const loading = ref(false)
const loadErrorMessage = ref('')
const approving = ref(false)
const approveErrorMessage = ref('')
/** 勾选状态；键是草稿 id，与 Store 分开维护——勾选是纯界面状态，不是列表数据。 */
const selected = ref<Set<string>>(new Set())

function groupTitle(group: DraftGroup): string {
  return group.batchId === null
    ? group.items[0]!.title
    : t('approvalListView.batchTitle', { count: group.items.length })
}

function isSelected(draftId: string): boolean {
  return selected.value.has(draftId)
}

function toggle(draftId: string, checked: boolean): void {
  const next = new Set(selected.value)
  if (checked) next.add(draftId)
  else next.delete(draftId)
  selected.value = next
}

function stagedIdsIn(group: DraftGroup): string[] {
  return group.items.filter((item) => item.state === 'STAGED').map((item) => item.id)
}

function toggleAllInGroup(group: DraftGroup, checked: boolean): void {
  const next = new Set(selected.value)
  for (const id of stagedIdsIn(group)) {
    if (checked) next.add(id)
    else next.delete(id)
  }
  selected.value = next
}

function isAllSelectedInGroup(group: DraftGroup): boolean {
  const staged = stagedIdsIn(group)
  return staged.length > 0 && staged.every((id) => selected.value.has(id))
}

const canApprove = computed(() => selected.value.size > 0 && !approving.value)

async function loadList(): Promise<void> {
  loading.value = true
  loadErrorMessage.value = ''
  try {
    await draftsStore.loadDrafts({ state: 'STAGED' })
  } catch (error) {
    loadErrorMessage.value =
      error instanceof Error ? error.message : t('approvalListView.loadFailed')
  } finally {
    loading.value = false
  }
}

onMounted(loadList)

/** 单份子草稿的证据签发 + 应用；证据变量只在本函数作用域内存在。 */
async function approveOne(draftId: string): Promise<void> {
  const detail = await auth.callWithSessionRetry((sid) => fetchDraftDetail(sid, draftId))
  if (!detail.approvalEvidence) return
  const clientRequestId = `approve-batch-${draftId}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  const applied = await auth.callWithSessionRetry((sid) =>
    applyDraft(sid, draftId, {
      clientRequestId,
      draftVersion: detail.draftVersion,
      targetVersion: detail.targetVersion,
      approvalEvidence: detail.approvalEvidence!,
    }),
  )
  draftsStore.markApplied(applied.draft)
}

async function approveSelected(): Promise<void> {
  if (!canApprove.value) return
  approving.value = true
  approveErrorMessage.value = ''
  const ids = [...selected.value]
  try {
    // 逐个应用而不是并发：并发对同一批次里不同商品互不冲突，但保持顺序更容易
    // 让商家从错误信息里判断到底是哪一份失败——批量场景优先可读性而非速度。
    for (const id of ids) {
      await approveOne(id)
      selected.value.delete(id)
    }
  } catch (error) {
    approveErrorMessage.value =
      error instanceof Error ? error.message : t('approvalListView.approveFailed')
  } finally {
    approving.value = false
  }
}
</script>

<template>
  <section class="approval-list-view">
    <h1>{{ t('approvalListView.title') }}</h1>

    <p v-if="loading">{{ t('approvalListView.loading') }}</p>
    <p v-else-if="loadErrorMessage" role="alert">{{ loadErrorMessage }}</p>
    <p v-else-if="draftsStore.groupedItems.length === 0">
      {{ t('approvalListView.empty') }}
    </p>

    <template v-else>
      <article
        v-for="group in draftsStore.groupedItems"
        :key="group.batchId ?? group.items[0]!.id"
        data-test="draft-group"
        class="approval-list-view__group"
      >
        <header class="approval-list-view__group-header">
          <label v-if="group.batchId !== null">
            <input
              type="checkbox"
              :data-test="`select-all-${group.batchId}`"
              :checked="isAllSelectedInGroup(group)"
              @change="toggleAllInGroup(group, ($event.target as HTMLInputElement).checked)"
            />
            {{ groupTitle(group) }}
          </label>
          <span v-else>{{ groupTitle(group) }}</span>
        </header>

        <ul class="approval-list-view__items">
          <li v-for="item in group.items" :key="item.id">
            <label>
              <input
                type="checkbox"
                :data-test="`select-${item.id}`"
                :disabled="item.state !== 'STAGED'"
                :checked="isSelected(item.id)"
                @change="toggle(item.id, ($event.target as HTMLInputElement).checked)"
              />
              {{ item.title }}
              <span class="approval-list-view__state">{{ item.state }}</span>
            </label>
            <RouterLink :to="{ name: 'approval', params: { draftId: item.id } }">
              {{ t('approvalListView.viewDetail') }}
            </RouterLink>
          </li>
        </ul>
      </article>

      <p v-if="approveErrorMessage" role="alert">{{ approveErrorMessage }}</p>

      <button
        type="button"
        data-test="approve-selected"
        :disabled="!canApprove"
        @click="approveSelected"
      >
        {{ approving ? t('approvalListView.approving') : t('approvalListView.approveSelected') }}
      </button>
    </template>
  </section>
</template>

<style scoped>
.approval-list-view {
  padding: var(--space-6);
}

.approval-list-view__group {
  margin-bottom: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  padding: var(--space-4);
}

.approval-list-view__group-header {
  font-weight: var(--font-weight-title);
  margin-bottom: var(--space-2);
}

.approval-list-view__items {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: var(--space-2);
}

.approval-list-view__state {
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}
</style>
