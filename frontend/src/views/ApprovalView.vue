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
  <section class="approval-view">
    <h1>{{ t('approvalView.title') }}</h1>

    <p v-if="loading">{{ t('approvalView.loading') }}</p>
    <p v-else-if="loadErrorMessage" role="alert">{{ loadErrorMessage }}</p>

    <template v-else-if="detail">
      <dl class="approval-view__meta">
        <dt>{{ t('approvalView.draftVersion') }}</dt>
        <dd data-test="draft-version">{{ detail.draftVersion }}</dd>
        <dt>{{ t('approvalView.targetVersion') }}</dt>
        <dd data-test="target-version">{{ detail.targetVersion }}</dd>
        <dt>{{ t('approvalView.stagedAt') }}</dt>
        <dd>{{ formatDate(detail.createdAt, localeStore.locale) }}</dd>
        <dt>{{ t('approvalView.expiresAt') }}</dt>
        <dd>{{ formatDate(detail.expiresAt, localeStore.locale) }}</dd>
      </dl>

      <h2>{{ t('approvalView.diffTitle') }}</h2>
      <p v-if="detail.kind === 'AFTER_SALE_DECISION'" role="note">
        {{ t('approvalView.afterSaleAmountNote') }}
      </p>
      <table class="approval-view__diff">
        <thead>
          <tr>
            <th>{{ t('approvalView.diffField') }}</th>
            <th>{{ t('approvalView.diffBefore') }}</th>
            <th>{{ t('approvalView.diffAfter') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in detail.diff" :key="entry.entryId" data-test="diff-row">
            <td>{{ entry.field }}</td>
            <td>{{ formatDiffValue(entry, entry.before) }}</td>
            <td>
              {{ formatDiffValue(entry, entry.after) }}
              <span v-if="entry.isPreview">{{ t('approvalView.diffPreviewNote') }}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <h2>{{ t('approvalView.guardrailTitle') }}</h2>
      <p>{{ t('approvalView.guardrailNote') }}</p>
      <ul class="approval-view__guardrails">
        <li v-for="check in detail.guardrailChecks" :key="check.code">
          <strong>{{ check.code }}</strong>
          —
          {{ check.passed ? t('approvalView.guardrailPassed') : t('approvalView.guardrailFailed') }}
          <template v-if="!check.passed">
            <span v-if="check.currentLimit">{{ check.currentLimit }}</span>
            <span v-if="check.remediation">{{ check.remediation }}</span>
          </template>
        </li>
      </ul>

      <p v-if="applyErrorMessage" role="alert">{{ applyErrorMessage }}</p>
      <p v-if="applySucceeded">{{ t('approvalView.applySucceeded') }}</p>

      <button data-test="approve" type="button" :disabled="!canApprove" @click="approve">
        {{ applying ? t('approvalView.approving') : t('approvalView.approve') }}
      </button>
    </template>
  </section>
</template>
