<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'

import { useSignalsStore } from '@/stores/signals'
import type { CustomerSignal } from '@/types/afterSales'

const store = useSignalsStore()
const { items, includeIgnored, nextCursor, loading, errorMessage } = storeToRefs(store)
const { t } = useI18n()
const reasons = ref<Record<string, string>>({})

function kindLabel(kind: CustomerSignal['kind']): string {
  return t(`signalsView.${{
    RETURN_REQUESTS: 'kindReturn', REFUND_REQUESTS: 'kindRefund',
    SUPPORT_TICKETS: 'kindTicket', CONTENT_GAP: 'kindContentGap',
  }[kind]}`)
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
  <section class="signals-view">
    <h1>{{ t('signalsView.title') }}</h1>
    <label><input v-model="includeIgnored" type="checkbox" />{{ t('signalsView.includeIgnored') }}</label>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <p v-if="!loading && items.length === 0">{{ t('signalsView.empty') }}</p>
    <ul class="signals-view__list">
      <li v-for="item in items" :key="item.id">
        <strong>{{ kindLabel(item.kind) }}</strong> · {{ item.productName ?? '—' }} ·
        {{ t('signalsView.count') }} {{ item.count }} · {{ item.signalDate }}
        <p v-if="item.isIgnored">{{ t('signalsView.ignored') }}：{{ item.ignoreReason }}</p>
        <div v-else>
          <label>{{ t('signalsView.reason') }}
            <input v-model="reasons[item.id]" type="text" maxlength="500" />
          </label>
          <button type="button" :disabled="!reasons[item.id]?.trim() || loading" @click="ignore(item.id)">
            {{ t('signalsView.ignore') }}
          </button>
        </div>
      </li>
    </ul>
    <button v-if="nextCursor" type="button" :disabled="loading" @click="store.load(nextCursor)">
      {{ t('signalsView.loadMore') }}
    </button>
  </section>
</template>

<style scoped>
.signals-view { max-width: 920px; margin: 0 auto; padding: var(--space-5); }
.signals-view__list { list-style: none; padding: 0; display: grid; gap: var(--space-3); }
.signals-view__list li { border: 1px solid var(--color-border); border-radius: var(--radius-card); padding: var(--space-4); }
.signals-view__list input { max-width: 100%; }
</style>
