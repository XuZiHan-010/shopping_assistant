<script setup lang="ts">
/**
 * 顾客信号（W Task 10 换成工作区版式）：按日汇总的退货、退款、工单与内容缺口卡片。
 * 忽略须填写原因；顾客已脱敏，本页不显示任何顾客标识。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'

import StatusPill from '@/components/layout/StatusPill.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import { useLocaleStore } from '@/stores/locale'
import { useSignalsStore } from '@/stores/signals'
import type { CustomerSignal } from '@/types/afterSales'
import { formatNumber } from '@/utils/localizedFormat'

const store = useSignalsStore()
const { items, includeIgnored, nextCursor, loading, errorMessage } = storeToRefs(store)
const { t } = useI18n()
const localeStore = useLocaleStore()
const locale = computed(() => localeStore.locale)
const reasons = ref<Record<string, string>>({})

function kindLabel(kind: CustomerSignal['kind']): string {
  return t(
    `signalsView.${
      {
        RETURN_REQUESTS: 'kindReturn',
        REFUND_REQUESTS: 'kindRefund',
        SUPPORT_TICKETS: 'kindTicket',
        CONTENT_GAP: 'kindContentGap',
      }[kind]
    }`,
  )
}

async function ignore(id: string): Promise<void> {
  const reason = reasons.value[id]?.trim()
  if (!reason) return
  try {
    await store.ignore(id, reason)
  } catch {
    // Store 的错误由视图统一展示，保留原因以便同一幂等键重试。
  }
}

onMounted(() => void store.load())
watch(includeIgnored, () => void store.load())
</script>

<template>
  <WorkspacePage title-id="page-title-signals" :title="t('signalsView.title')">
    <template #intro>
      <p>{{ t('signalsView.sub') }}</p>
    </template>

    <div class="ws-toolbar">
      <label class="ws-check">
        <input v-model="includeIgnored" type="checkbox" />{{ t('signalsView.includeIgnored') }}
      </label>
    </div>
    <p v-if="errorMessage" class="ws-alert" role="alert">{{ errorMessage }}</p>
    <div v-if="!loading && items.length === 0" class="ws-panel">
      <p class="ws-state">{{ t('signalsView.empty') }}</p>
    </div>

    <ul class="signals-view__list">
      <li
        v-for="item in items"
        :key="item.id"
        class="ws-panel signal"
        :class="{ 'signal--ignored': item.isIgnored }"
      >
        <div class="signal__head">
          <strong class="signal__kind">{{ kindLabel(item.kind) }}</strong>
          <span class="ws-sub">{{ item.signalDate }}</span>
        </div>
        <div class="signal__big">
          <span class="signal__count">{{ formatNumber(item.count, locale) }}</span>
          <small>{{ t('signalsView.count') }}</small>
        </div>
        <p class="signal__product">{{ item.productName ?? '—' }}</p>

        <p v-if="item.isIgnored" class="signal__ignored">
          <StatusPill tone="muted">{{ t('signalsView.ignored') }}</StatusPill>
          <span>{{ item.ignoreReason }}</span>
        </p>
        <div v-else class="signal__form">
          <label class="ws-field signal__field">
            {{ t('signalsView.reason') }}
            <input v-model="reasons[item.id]" class="ws-input" type="text" maxlength="500" />
          </label>
          <button
            type="button"
            class="ws-btn ws-btn--sm"
            :disabled="!reasons[item.id]?.trim() || loading"
            @click="ignore(item.id)"
          >
            {{ t('signalsView.ignore') }}
          </button>
        </div>
      </li>
    </ul>
    <div v-if="nextCursor" class="load-more">
      <button
        type="button"
        class="ws-btn ws-btn--sm"
        :disabled="loading"
        @click="store.load(nextCursor)"
      >
        {{ t('signalsView.loadMore') }}
      </button>
    </div>
  </WorkspacePage>
</template>

<style scoped>
.signals-view__list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  gap: 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* 卡片之间用 grid 的 gap，不要 .ws-panel + .ws-panel 的纵向外边距 */
.signals-view__list > .signal {
  margin-top: 0;
}

.signal {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 16px 18px;
  overflow-wrap: anywhere;
}

.signal--ignored {
  background: var(--well);
  box-shadow: none;
}

.signal__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px 10px;
  font-size: 13px;
}

.signal__head .ws-sub {
  display: inline;
  font-variant-numeric: tabular-nums;
}

.signal__big {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.signal__count {
  font-size: 28px;
  font-weight: 650;
  line-height: 1;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.signal__big small {
  font-size: 13px;
  color: var(--ink-soft);
}

.signal__product {
  margin: 0;
  font-size: 13.5px;
  color: var(--ink-2);
}

.signal__ignored {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
  margin: auto 0 0;
  padding-top: 6px;
  font-size: 12.5px;
  color: var(--ink-2);
}

.signal__form {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 8px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--line);
}

.signal__field {
  flex: 1 1 180px;
  flex-direction: column;
  align-items: stretch;
  font-weight: 500;
  color: var(--ink-soft);
}

.signal__field .ws-input {
  width: 100%;
}

.load-more {
  display: flex;
  justify-content: center;
  margin-top: 14px;
}
</style>
