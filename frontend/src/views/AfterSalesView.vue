<script setup lang="ts">
/**
 * 售后队列（W Task 10 换成工作区版式）：列表与详情，宽屏并排、窄屏上下排。
 *
 * 顾客只以店铺级脱敏别名出现（R5）；同意、拒绝都经助手起草、审批页批准，本页只把问题
 * 预填进助手栏（`rail.ask()`），不代为发送、批准或执行。
 */
import { Sparkles } from '@lucide/vue'
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'

import type { PillTone } from '@/components/layout/pillTone'
import StatusPill from '@/components/layout/StatusPill.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import { useAfterSalesStore } from '@/stores/afterSales'
import { useLocaleStore } from '@/stores/locale'
import { useRailStore } from '@/stores/rail'
import type { AfterSaleState, MerchantAfterSale } from '@/types/afterSales'
import { formatCurrency, formatDate } from '@/utils/localizedFormat'

const store = useAfterSalesStore()
const { items, detail, nextCursor, loading, errorMessage, stateFilter } = storeToRefs(store)
const locale = useLocaleStore()
const rail = useRailStore()
const { t } = useI18n()

const states: AfterSaleState[] = [
  'PENDING_MERCHANT',
  'AWAITING_CUSTOMER_INFO',
  'APPROVED',
  'AWAITING_RETURN',
  'RECEIVED',
  'REFUNDED',
  'REJECTED',
  'CLOSED',
]

function stateLabel(state: AfterSaleState): string {
  const key = {
    PENDING_MERCHANT: 'statePending',
    APPROVED: 'stateApproved',
    REJECTED: 'stateRejected',
    AWAITING_RETURN: 'stateAwaitingReturn',
    RECEIVED: 'stateReceived',
    REFUNDED: 'stateRefunded',
    AWAITING_CUSTOMER_INFO: 'stateAwaitingInfo',
    CLOSED: 'stateClosed',
  }[state]
  return t(`afterSalesView.${key}`)
}

/** 售后状态 → 胶囊色调（纯展示）：待商家处理最醒目，终态淡化。 */
function stateTone(state: AfterSaleState): PillTone {
  if (state === 'PENDING_MERCHANT') return 'warn'
  if (state === 'AWAITING_CUSTOMER_INFO' || state === 'AWAITING_RETURN') return 'info'
  if (state === 'APPROVED' || state === 'RECEIVED') return 'violet'
  if (state === 'REFUNDED') return 'ok'
  return 'muted'
}

function typeLabel(type: MerchantAfterSale['type']): string {
  return t(
    `afterSalesView.${
      {
        RETURN_REFUND: 'typeReturn',
        REFUND_ONLY: 'typeRefund',
        TICKET: 'typeTicket',
      }[type]
    }`,
  )
}

function draft(): void {
  if (!detail.value) return
  // 经 `opsChat.prefill()` 预填并打开常驻外壳的助手栏，留在售后页，不代为发送（W Task 6）。
  rail.ask(t('afterSalesView.draftPrompt', { id: detail.value.id }))
}

function changeFilter(value: string): void {
  stateFilter.value = value as AfterSaleState | ''
  void store.load()
}

onMounted(() => void store.load())
</script>

<template>
  <WorkspacePage title-id="page-title-after-sales" :title="t('afterSalesView.title')">
    <template #intro>
      <p>{{ t('afterSalesView.sub') }}</p>
    </template>

    <div class="ws-toolbar">
      <label class="ws-field">
        {{ t('afterSalesView.stateFilter') }}
        <select
          class="ws-select"
          :value="stateFilter"
          @change="changeFilter(($event.target as HTMLSelectElement).value)"
        >
          <option value="">{{ t('afterSalesView.allStates') }}</option>
          <option v-for="state in states" :key="state" :value="state">
            {{ stateLabel(state) }}
          </option>
        </select>
      </label>
    </div>
    <p v-if="errorMessage" class="ws-alert" role="alert">{{ errorMessage }}</p>

    <div class="layout" :class="{ 'layout--split': detail }">
      <div class="ws-panel queue">
        <p v-if="!loading && items.length === 0" class="ws-state">
          {{ t('afterSalesView.empty') }}
        </p>
        <ul class="after-sales-view__list">
          <li v-for="item in items" :key="item.id">
            <button
              type="button"
              class="case"
              :aria-current="detail?.id === item.id ? 'true' : undefined"
              @click="store.open(item.id)"
            >
              <span class="case__main">
                <strong class="case__type">{{ typeLabel(item.type) }}</strong>
                <span class="ws-alias" translate="no">{{ item.buyerAlias }}</span>
              </span>
              <StatusPill :tone="stateTone(item.state)">{{ stateLabel(item.state) }}</StatusPill>
            </button>
          </li>
        </ul>
        <div v-if="nextCursor" class="ws-more">
          <button
            type="button"
            class="ws-btn ws-btn--sm"
            :disabled="loading"
            @click="store.load(nextCursor)"
          >
            {{ t('afterSalesView.loadMore') }}
          </button>
        </div>
      </div>

      <article v-if="detail" class="ws-panel after-sales-view__detail">
        <header class="detail__head">
          <h2>{{ t('afterSalesView.detail') }}</h2>
          <span class="detail__pills">
            <StatusPill tone="muted">{{ typeLabel(detail.type) }}</StatusPill>
            <StatusPill :tone="stateTone(detail.state)">{{ stateLabel(detail.state) }}</StatusPill>
          </span>
        </header>
        <dl class="facts">
          <dt>{{ t('afterSalesView.order') }}</dt>
          <dd class="ws-mono" translate="no">{{ detail.orderId }}</dd>
          <dt>{{ t('afterSalesView.reason') }}</dt>
          <dd>{{ detail.reason }}</dd>
          <dt>{{ t('afterSalesView.customer') }}</dt>
          <dd>
            <span class="ws-alias" translate="no">{{ detail.buyerAlias }}</span>
          </dd>
          <dt>{{ t('afterSalesView.firstResponseDue') }}</dt>
          <dd>{{ formatDate(detail.firstResponseDueAt, locale.locale) }}</dd>
          <dt>{{ t('afterSalesView.refund') }}</dt>
          <dd class="num">
            {{
              detail.refundAmountCents === null
                ? '—'
                : formatCurrency(detail.refundAmountCents / 100, locale.locale)
            }}
          </dd>
        </dl>

        <h3>{{ t('afterSalesView.lines') }}</h3>
        <ul class="plain">
          <li v-for="line in detail.lines" :key="line.orderItemId">
            {{ line.name }} × {{ line.quantity }}
          </li>
        </ul>
        <h3>{{ t('afterSalesView.events') }}</h3>
        <ol class="timeline">
          <li v-for="event in detail.events" :key="event.id">
            <strong>{{ stateLabel(event.toState) }}</strong>
            <span class="ws-sub">{{ formatDate(event.occurredAt, locale.locale) }}</span>
          </li>
        </ol>
        <h3>{{ t('afterSalesView.supplements') }}</h3>
        <ul class="plain">
          <li v-for="item in detail.supplements" :key="item.id">{{ item.note }}</li>
        </ul>
        <h3>{{ t('afterSalesView.replies') }}</h3>
        <ul class="plain">
          <li v-for="item in detail.replies" :key="item.id">{{ item.text }}</li>
        </ul>
        <h3>{{ t('afterSalesView.summary') }}</h3>
        <p v-if="detail.conversationSummary.status === 'AVAILABLE'" class="quote">
          {{ detail.conversationSummary.text }}
        </p>
        <p v-else-if="detail.conversationSummary.status === 'UNAVAILABLE'" class="muted">
          {{ t('afterSalesView.summaryUnavailable') }}
        </p>
        <p v-else class="muted">{{ t('afterSalesView.summaryNotShared') }}</p>

        <div class="detail__actions">
          <button
            type="button"
            class="ws-btn ws-btn--primary ws-btn--sm"
            data-test="draft-after-sale"
            @click="draft"
          >
            <Sparkles :size="14" aria-hidden="true" />
            <span>{{ t('afterSalesView.draft') }}</span>
          </button>
        </div>
      </article>
    </div>
  </WorkspacePage>
</template>

<style scoped>
.layout {
  display: grid;
  gap: 14px;
  align-items: start;
}

.layout > .ws-panel + .ws-panel {
  margin-top: 0;
}

@media (min-width: 1100px) {
  .layout--split {
    grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  }
}

.queue {
  overflow: hidden;
}

.after-sales-view__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.after-sales-view__list li + li {
  border-top: 1px solid var(--line);
}

.case {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 11px 18px;
  background: none;
  color: var(--ink);
  text-align: left;
}

.case:hover {
  background: var(--hover);
}

.case[aria-current='true'] {
  background: var(--well);
  box-shadow: inset 3px 0 0 var(--accent);
}

.case__main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  min-width: 0;
}

.case__type {
  font-size: 13.5px;
  font-weight: 600;
}

.after-sales-view__detail {
  padding: 16px 18px 18px;
  overflow-wrap: anywhere;
}

.detail__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.detail__head h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
}

.detail__pills {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}

.facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 7px 16px;
  margin: 14px 0 4px;
  font-size: 13px;
}

.facts dt {
  color: var(--ink-soft);
}

.facts dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}

.num {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

h3 {
  margin: 16px 0 6px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--ink-soft);
}

.plain {
  margin: 0;
  padding: 0 0 0 18px;
  font-size: 13px;
  color: var(--ink-2);
}

.timeline {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0 0 0 14px;
  border-left: 2px solid var(--line-strong);
  list-style: none;
  font-size: 13px;
}

.timeline li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
}

.timeline .ws-sub {
  display: inline;
}

.quote {
  margin: 0;
  padding: 7px 10px;
  border-left: 2px solid var(--line-strong);
  border-radius: 0 8px 8px 0;
  background: var(--well);
  font-size: 13px;
  color: var(--ink-2);
}

.muted {
  margin: 0;
  font-size: 13px;
  color: var(--ink-soft);
}

.detail__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

@media (max-width: 520px) {
  .facts {
    grid-template-columns: minmax(0, 1fr);
    gap: 2px;
  }

  .facts dd {
    margin-bottom: 6px;
  }

  .detail__actions .ws-btn {
    width: 100%;
    height: auto;
    min-height: 34px;
    white-space: normal;
  }
}
</style>
