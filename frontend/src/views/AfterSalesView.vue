<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { useAfterSalesStore } from '@/stores/afterSales'
import { useLocaleStore } from '@/stores/locale'
import { useOpsChatStore } from '@/stores/opsChat'
import type { AfterSaleState, MerchantAfterSale } from '@/types/afterSales'
import { formatCurrency, formatDate } from '@/utils/localizedFormat'

const store = useAfterSalesStore()
const { items, detail, nextCursor, loading, errorMessage, stateFilter } = storeToRefs(store)
const locale = useLocaleStore()
const chat = useOpsChatStore()
const router = useRouter()
const { t } = useI18n()

const states: AfterSaleState[] = [
  'PENDING_MERCHANT', 'AWAITING_CUSTOMER_INFO', 'APPROVED', 'AWAITING_RETURN',
  'RECEIVED', 'REFUNDED', 'REJECTED', 'CLOSED',
]

function stateLabel(state: AfterSaleState): string {
  const key = {
    PENDING_MERCHANT: 'statePending', APPROVED: 'stateApproved', REJECTED: 'stateRejected',
    AWAITING_RETURN: 'stateAwaitingReturn', RECEIVED: 'stateReceived',
    REFUNDED: 'stateRefunded', AWAITING_CUSTOMER_INFO: 'stateAwaitingInfo',
    CLOSED: 'stateClosed',
  }[state]
  return t(`afterSalesView.${key}`)
}

function typeLabel(type: MerchantAfterSale['type']): string {
  return t(`afterSalesView.${{
    RETURN_REFUND: 'typeReturn', REFUND_ONLY: 'typeRefund', TICKET: 'typeTicket',
  }[type]}`)
}

function draft(): void {
  if (!detail.value) return
  chat.prefill(`请查看售后事项 ${detail.value.id}，根据平台规则起草处理决定和客服回复。`)
  void router.push({ name: 'assistant' })
}

function changeFilter(value: string): void {
  stateFilter.value = value as AfterSaleState | ''
  void store.load()
}

onMounted(() => void store.load())
</script>

<template>
  <section class="after-sales-view">
    <h1>{{ t('afterSalesView.title') }}</h1>
    <label>
      {{ t('afterSalesView.stateFilter') }}
      <select :value="stateFilter" @change="changeFilter(($event.target as HTMLSelectElement).value)">
        <option value="">{{ t('afterSalesView.allStates') }}</option>
        <option v-for="state in states" :key="state" :value="state">{{ stateLabel(state) }}</option>
      </select>
    </label>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <p v-if="!loading && items.length === 0">{{ t('afterSalesView.empty') }}</p>
    <ul class="after-sales-view__list">
      <li v-for="item in items" :key="item.id">
        <button type="button" @click="store.open(item.id)">
          {{ typeLabel(item.type) }} · {{ stateLabel(item.state) }} · {{ item.buyerAlias }}
        </button>
      </li>
    </ul>
    <button v-if="nextCursor" type="button" :disabled="loading" @click="store.load(nextCursor)">
      {{ t('afterSalesView.loadMore') }}
    </button>

    <article v-if="detail" class="after-sales-view__detail">
      <h2>{{ t('afterSalesView.detail') }}</h2>
      <dl>
        <dt>{{ t('afterSalesView.order') }}</dt><dd>{{ detail.orderId }}</dd>
        <dt>{{ t('afterSalesView.reason') }}</dt><dd>{{ detail.reason }}</dd>
        <dt>{{ t('afterSalesView.customer') }}</dt><dd>{{ detail.buyerAlias }}</dd>
        <dt>{{ t('afterSalesView.firstResponseDue') }}</dt>
        <dd>{{ formatDate(detail.firstResponseDueAt, locale.locale) }}</dd>
        <dt>{{ t('afterSalesView.refund') }}</dt>
        <dd>{{ detail.refundAmountCents === null ? '—' : formatCurrency(detail.refundAmountCents / 100, locale.locale) }}</dd>
      </dl>
      <h3>{{ t('afterSalesView.lines') }}</h3>
      <ul><li v-for="line in detail.lines" :key="line.orderItemId">{{ line.name }} × {{ line.quantity }}</li></ul>
      <h3>{{ t('afterSalesView.events') }}</h3>
      <ol><li v-for="event in detail.events" :key="event.id">{{ stateLabel(event.toState) }} · {{ formatDate(event.occurredAt, locale.locale) }}</li></ol>
      <h3>{{ t('afterSalesView.supplements') }}</h3>
      <ul><li v-for="item in detail.supplements" :key="item.id">{{ item.note }}</li></ul>
      <h3>{{ t('afterSalesView.replies') }}</h3>
      <ul><li v-for="item in detail.replies" :key="item.id">{{ item.text }}</li></ul>
      <h3>{{ t('afterSalesView.summary') }}</h3>
      <p v-if="detail.conversationSummary.status === 'AVAILABLE'">{{ detail.conversationSummary.text }}</p>
      <p v-else-if="detail.conversationSummary.status === 'UNAVAILABLE'">{{ t('afterSalesView.summaryUnavailable') }}</p>
      <p v-else>{{ t('afterSalesView.summaryNotShared') }}</p>
      <button type="button" data-test="draft-after-sale" @click="draft">
        {{ t('afterSalesView.draft') }}
      </button>
    </article>
  </section>
</template>

<style scoped>
.after-sales-view { max-width: 920px; margin: 0 auto; padding: var(--space-5); }
.after-sales-view__list { list-style: none; padding: 0; display: grid; gap: var(--space-2); }
.after-sales-view__list button { width: 100%; text-align: left; }
.after-sales-view__detail { margin-top: var(--space-5); padding: var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-card); }
dl { display: grid; grid-template-columns: max-content 1fr; gap: var(--space-2) var(--space-4); }
dd { margin: 0; overflow-wrap: anywhere; }
@media (max-width: 520px) { dl { grid-template-columns: 1fr; } }
</style>
