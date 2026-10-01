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

import {
  applyDraft,
  fetchDraftDetail,
  type DraftKind,
  type DraftState,
} from '@/api/adapters/merchantOps'
import type { PillTone } from '@/components/layout/pillTone'
import StatusPill from '@/components/layout/StatusPill.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import { useAuthStore } from '@/stores/auth'
import { useDraftsStore, type DraftGroup } from '@/stores/drafts'
import { useLocaleStore } from '@/stores/locale'
import { formatDate } from '@/utils/localizedFormat'

const auth = useAuthStore()
const draftsStore = useDraftsStore()
const localeStore = useLocaleStore()
const { t } = useI18n()

/** 草稿状态 → 胶囊色调；文案键 `approvalListView.state.*`（纯展示，不参与勾选与批准逻辑）。 */
const STATE_TONES: Record<DraftState, PillTone> = {
  STAGED: 'warn',
  APPLIED: 'ok',
  DISCARDED: 'muted',
  EXPIRED: 'muted',
}

function stateLabel(state: DraftState): string {
  return state in STATE_TONES ? t(`approvalListView.state.${state}`) : state
}

function stateTone(state: DraftState): PillTone {
  return STATE_TONES[state] ?? 'muted'
}

const KNOWN_KINDS: readonly DraftKind[] = [
  'RESTOCK',
  'CONTENT_CHANGE',
  'PRICE_CHANGE',
  'COUPON',
  'AFTER_SALE_DECISION',
]

function kindLabel(kind: DraftKind): string {
  return KNOWN_KINDS.includes(kind) ? t(`approvalListView.kind.${kind}`) : kind
}

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
  <WorkspacePage title-id="page-title-approvals" :title="t('approvalListView.title')">
    <template #intro>
      <p>{{ t('approvalListView.sub') }}</p>
    </template>

    <div v-if="loading" class="ws-panel">
      <p class="ws-state" role="status">{{ t('approvalListView.loading') }}</p>
    </div>
    <div v-else-if="loadErrorMessage" class="ws-panel">
      <p class="ws-state" role="alert">{{ loadErrorMessage }}</p>
    </div>
    <div v-else-if="draftsStore.groupedItems.length === 0" class="ws-panel">
      <p class="ws-state">{{ t('approvalListView.empty') }}</p>
    </div>

    <template v-else>
      <div class="ws-toolbar">
        <span class="selection">
          {{ t('approvalListView.selectedCount', { count: selected.size }) }}
        </span>
        <span class="ws-toolbar__spacer" />
        <button
          type="button"
          class="ws-btn ws-btn--primary ws-btn--sm"
          data-test="approve-selected"
          :disabled="!canApprove"
          @click="approveSelected"
        >
          {{ approving ? t('approvalListView.approving') : t('approvalListView.approveSelected') }}
        </button>
      </div>

      <p v-if="approveErrorMessage" class="ws-alert" role="alert">{{ approveErrorMessage }}</p>

      <article
        v-for="group in draftsStore.groupedItems"
        :key="group.batchId ?? group.items[0]!.id"
        data-test="draft-group"
        class="ws-panel batch"
      >
        <!-- 单独一份的草稿不另起组标题（组标题就是它自己的标题），只给批次加「全选」表头。 -->
        <header v-if="group.batchId !== null" class="batch__head">
          <label class="ws-check batch__all">
            <input
              type="checkbox"
              :data-test="`select-all-${group.batchId}`"
              :checked="isAllSelectedInGroup(group)"
              @change="toggleAllInGroup(group, ($event.target as HTMLInputElement).checked)"
            />
            <span class="batch__title">{{ groupTitle(group) }}</span>
          </label>
          <StatusPill tone="violet">
            {{ t('approvalListView.batchLabel') }}
          </StatusPill>
        </header>

        <ul class="batch__items">
          <li v-for="item in group.items" :key="item.id" class="draft">
            <label class="draft__pick">
              <input
                type="checkbox"
                :data-test="`select-${item.id}`"
                :disabled="item.state !== 'STAGED'"
                :checked="isSelected(item.id)"
                @change="toggle(item.id, ($event.target as HTMLInputElement).checked)"
              />
              <span class="draft__title">{{ item.title }}</span>
            </label>
            <span class="draft__meta">
              <StatusPill tone="muted">{{ kindLabel(item.kind) }}</StatusPill>
              <StatusPill :tone="stateTone(item.state)">{{ stateLabel(item.state) }}</StatusPill>
              <span class="ws-sub">
                {{ t('approvalView.expiresAt') }}
                {{ formatDate(item.expiresAt, localeStore.locale) }}
              </span>
            </span>
            <RouterLink
              class="ws-btn ws-btn--sm draft__open"
              :to="{ name: 'approval', params: { draftId: item.id } }"
            >
              {{ t('approvalListView.viewDetail') }}
            </RouterLink>
          </li>
        </ul>
      </article>
    </template>
  </WorkspacePage>
</template>

<style scoped>
.selection {
  font-size: 12.5px;
  color: var(--ink-soft);
}

.batch {
  overflow: hidden;
}

.batch__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--line);
  background: var(--well);
  font-size: 13px;
}

.batch__title {
  min-width: 0;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.batch__items {
  margin: 0;
  padding: 0;
  list-style: none;
}

.draft {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px 14px;
  padding: 12px 18px;
  border-top: 1px solid var(--line);
}

.draft:first-child {
  border-top: 0;
}

.draft__pick {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
}

.draft__pick input {
  flex-shrink: 0;
  margin-top: 2px;
}

.draft__title {
  min-width: 0;
  overflow-wrap: anywhere;
}

.draft__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
  grid-column: 1;
  padding-left: 26px;
}

.draft__meta .ws-sub {
  display: inline;
}

.draft__open {
  grid-column: 2;
  grid-row: 1 / span 2;
}

@media (max-width: 520px) {
  .draft {
    grid-template-columns: minmax(0, 1fr);
  }

  .draft__open {
    grid-column: 1;
    grid-row: auto;
    justify-self: start;
    margin-left: 26px;
  }
}
</style>
