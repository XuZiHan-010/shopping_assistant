<script setup lang="ts">
/**
 * 商家端所有写操作的唯一出口（PRD D9）。也是审批证据唯一的合法消费者
 * （契约计划 §8.7.9）。
 *
 * **审批证据只存本组件的内存 `ref`，绝不写入 Pinia Store**——Store 会被
 * devtools 与持久化插件看到，证据是一次性、短期有效的敏感值。`stores/drafts.ts`
 * 只在批准成功后收到不含证据的 `DraftSummary`，用于同步列表。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  applyDraft,
  fetchDraftDetail,
  type DraftDetail,
  type DraftDiffEntry,
} from '@/api/adapters/merchantOps'
import { AppError } from '@/api/errors'
import StatusPill from '@/components/layout/StatusPill.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import { useAuthStore } from '@/stores/auth'
import { useDraftsStore } from '@/stores/drafts'
import { useLocaleStore } from '@/stores/locale'
import { describeError } from '@/utils/errorCopy'
import { formatCurrency, formatDate } from '@/utils/localizedFormat'

const props = defineProps<{ draftId: string }>()

const auth = useAuthStore()
const draftsStore = useDraftsStore()
const localeStore = useLocaleStore()
const { t } = useI18n()

const detail = ref<DraftDetail | undefined>(undefined)
const loading = ref(false)
const loadErrorMessage = ref('')
const applyErrorMessage = ref('')
const applying = ref(false)
const applySucceeded = ref(false)
/** 同一次批准点击（含内部网络重试）复用同一个值；每次新点击重新生成。 */
let currentClientRequestId = ''

const guardrailsPassed = computed(
  () => detail.value?.guardrailChecks.every((check) => check.passed) ?? false,
)

const canApprove = computed(
  () =>
    !!detail.value &&
    detail.value.state === 'STAGED' &&
    !!detail.value.approvalEvidence &&
    guardrailsPassed.value &&
    !applying.value,
)

function formatDiffValue(entry: DraftDiffEntry, value: string | number | boolean | null): string {
  if (value === null) return '—'
  if (entry.unit === 'CENTS' && typeof value === 'number') {
    return formatCurrency(value / 100, localeStore.locale)
  }
  if (entry.unit === 'BPS' && typeof value === 'number') {
    return `${(value / 100).toFixed(2)}%`
  }
  if (entry.unit === 'BOOL') return value ? 'true' : 'false'
  return String(value)
}

async function loadDetail(): Promise<void> {
  loading.value = true
  loadErrorMessage.value = ''
  try {
    detail.value = await auth.callWithSessionRetry((sid) => fetchDraftDetail(sid, props.draftId))
  } catch (error) {
    loadErrorMessage.value = error instanceof Error ? error.message : t('approvalView.loadFailed')
  } finally {
    loading.value = false
  }
}

onMounted(loadDetail)

/**
 * `attempt` 只用来在网络层失败时重试一次，绝不用来重新生成
 * `client_request_id`——同一次用户点击，无论内部重试几次，服务端看到的必须
 * 是同一个幂等键（契约计划 §8.7.9）。
 */
async function submitApply(evidence: string, attempt = 1): Promise<void> {
  const current = detail.value
  if (!current) return
  try {
    const applied = await auth.callWithSessionRetry((sid) =>
      applyDraft(sid, props.draftId, {
        clientRequestId: currentClientRequestId,
        draftVersion: current.draftVersion,
        targetVersion: current.targetVersion,
        approvalEvidence: evidence,
      }),
    )
    detail.value = { ...current, state: applied.draft.state }
    draftsStore.markApplied(applied.draft)
    applyErrorMessage.value = ''
    applySucceeded.value = true
  } catch (error) {
    if (!(error instanceof AppError)) throw error

    if (error.code === 'NETWORK' && attempt < 2) {
      await submitApply(evidence, attempt + 1)
      return
    }
    if (error.code === 'CONFIRMATION_REQUIRED') {
      applyErrorMessage.value = t('approvalView.confirmationRequired')
      // 重新拉取详情取新证据；绝不用旧证据自动重试——那等于替商家批准了一个
      // 他没看过的版本。
      await loadDetail()
      return
    }
    // VERSION_CONFLICT / GUARDRAIL_REJECTED 等其余错误只展示，不自动重试：
    // 三者都 `retryable=false`，原样重发同一个请求不会成功。
    applyErrorMessage.value = describeError(error).detail
  }
}

async function approve(): Promise<void> {
  if (!canApprove.value || !detail.value?.approvalEvidence) return
  applying.value = true
  applySucceeded.value = false
  currentClientRequestId = `approve-${props.draftId}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  try {
    await submitApply(detail.value.approvalEvidence)
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <WorkspacePage title-id="page-title-approval" :title="t('approvalView.title')">
    <template v-if="detail" #intro>
      <p class="draft-title">{{ detail.title }}</p>
    </template>

    <div v-if="loading" class="ws-panel">
      <p class="ws-state" role="status">{{ t('approvalView.loading') }}</p>
    </div>
    <div v-else-if="loadErrorMessage" class="ws-panel">
      <p class="ws-state" role="alert">{{ loadErrorMessage }}</p>
    </div>

    <template v-else-if="detail">
      <dl class="meta">
        <div class="meta__item">
          <dt>{{ t('approvalView.draftVersion') }}</dt>
          <dd data-test="draft-version">{{ detail.draftVersion }}</dd>
        </div>
        <div class="meta__item">
          <dt>{{ t('approvalView.targetVersion') }}</dt>
          <dd data-test="target-version">{{ detail.targetVersion }}</dd>
        </div>
        <div class="meta__item">
          <dt>{{ t('approvalView.stagedAt') }}</dt>
          <dd>{{ formatDate(detail.createdAt, localeStore.locale) }}</dd>
        </div>
        <div class="meta__item">
          <dt>{{ t('approvalView.expiresAt') }}</dt>
          <dd>{{ formatDate(detail.expiresAt, localeStore.locale) }}</dd>
        </div>
      </dl>

      <section class="ws-panel block" aria-labelledby="approval-diff-title">
        <h2 id="approval-diff-title" class="block__title">{{ t('approvalView.diffTitle') }}</h2>
        <p v-if="detail.kind === 'AFTER_SALE_DECISION'" class="block__note" role="note">
          {{ t('approvalView.afterSaleAmountNote') }}
        </p>
        <table class="ws-table diff">
          <thead>
            <tr>
              <th scope="col">{{ t('approvalView.diffField') }}</th>
              <th scope="col">{{ t('approvalView.diffBefore') }}</th>
              <th scope="col">{{ t('approvalView.diffAfter') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in detail.diff" :key="entry.entryId" data-test="diff-row">
              <td class="diff__field ws-mono">{{ entry.field }}</td>
              <td class="diff__before" :data-label="t('approvalView.diffBefore')">
                {{ formatDiffValue(entry, entry.before) }}
              </td>
              <td class="diff__after" :data-label="t('approvalView.diffAfter')">
                {{ formatDiffValue(entry, entry.after) }}
                <span v-if="entry.isPreview" class="diff__preview">
                  {{ t('approvalView.diffPreviewNote') }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="ws-panel block" aria-labelledby="approval-guardrail-title">
        <h2 id="approval-guardrail-title" class="block__title">
          {{ t('approvalView.guardrailTitle') }}
        </h2>
        <p class="block__note">{{ t('approvalView.guardrailNote') }}</p>
        <ul class="checks">
          <li v-for="check in detail.guardrailChecks" :key="check.code" class="check">
            <StatusPill :tone="check.passed ? 'ok' : 'danger'">
              {{
                check.passed ? t('approvalView.guardrailPassed') : t('approvalView.guardrailFailed')
              }}
            </StatusPill>
            <strong class="ws-mono">{{ check.code }}</strong>
            <template v-if="!check.passed">
              <span v-if="check.currentLimit" class="check__detail">{{ check.currentLimit }}</span>
              <span v-if="check.remediation" class="check__detail">{{ check.remediation }}</span>
            </template>
          </li>
        </ul>
      </section>

      <div class="decision">
        <p v-if="applyErrorMessage" class="ws-alert" role="alert">{{ applyErrorMessage }}</p>
        <p v-if="applySucceeded" class="ws-success">{{ t('approvalView.applySucceeded') }}</p>
        <button
          data-test="approve"
          type="button"
          class="ws-btn ws-btn--primary"
          :disabled="!canApprove"
          @click="approve"
        >
          {{ applying ? t('approvalView.approving') : t('approvalView.approve') }}
        </button>
      </div>
    </template>
  </WorkspacePage>
</template>

<style scoped>
.draft-title {
  font-weight: 600;
}

.meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 0 0 14px;
}

.meta__item {
  min-width: 0;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--card);
}

.meta dt {
  font-size: 12px;
  color: var(--ink-soft);
}

.meta dd {
  margin: 2px 0 0;
  font-size: 13.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.block {
  overflow: hidden;
}

.block__title {
  margin: 0;
  padding: 14px 18px 4px;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 600;
}

.block__note {
  margin: 0;
  padding: 0 18px 10px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink-soft);
}

.diff {
  border-top: 1px solid var(--line);
}

.diff__field {
  color: var(--ink-2);
}

.diff__before {
  color: var(--ink-2);
}

.diff__after {
  font-weight: 600;
  color: var(--ok);
}

.diff__preview {
  display: block;
  font-size: 12px;
  font-weight: 400;
  color: var(--ink-soft);
}

.checks {
  margin: 0;
  padding: 0 0 6px;
  list-style: none;
  border-top: 1px solid var(--line);
}

.check {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  padding: 10px 18px;
  font-size: 13px;
}

.check + .check {
  border-top: 1px solid var(--line);
}

.check__detail {
  flex-basis: 100%;
  font-size: 12.5px;
  color: var(--ink-2);
  overflow-wrap: anywhere;
}

.decision {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0;
  margin-top: 16px;
}

.decision .ws-alert,
.decision .ws-success {
  align-self: stretch;
}

@media (max-width: 820px) {
  .meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .diff__field {
    grid-column: 1 / -1;
  }

  .diff__before::before,
  .diff__after::before {
    content: attr(data-label);
    display: block;
    font-size: 11.5px;
    font-weight: 400;
    color: var(--ink-soft);
  }

  .decision {
    align-items: stretch;
  }
}
</style>
