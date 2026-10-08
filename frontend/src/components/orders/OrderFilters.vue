<script setup lang="ts">
/**
 * 订单页三项筛选（契约 §8.12.4：payment_status / fulfillment_status / after_sale_status）。
 *
 * 只产出筛选值，不取数；空串表示「全部」（不过滤）。换筛选后从第一页重读、不带旧游标，
 * 由订单页负责（游标绑定筛选条件，§8.7.4）。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  AFTER_SALE_STATUSES,
  EMPTY_ORDER_FILTERS,
  FULFILLMENT_STATUSES,
  PAYMENT_STATUSES,
  type OrderFilterState,
} from './orderStatus'

const model = defineModel<OrderFilterState>({ required: true })

const { t } = useI18n()

const active = computed(
  () => model.value.payment !== '' || model.value.fulfillment !== '' || model.value.afterSale !== '',
)

function update<K extends keyof OrderFilterState>(key: K, event: Event): void {
  const value = (event.target as HTMLSelectElement).value as OrderFilterState[K]
  model.value = { ...model.value, [key]: value }
}

function clear(): void {
  model.value = { ...EMPTY_ORDER_FILTERS }
}
</script>

<template>
  <div class="filters" role="group" :aria-label="t('ordersPage.filtersLabel')">
    <label class="filters__field">
      <span>{{ t('ordersPage.filters.payment') }}</span>
      <select
        data-test="filter-payment"
        :value="model.payment"
        @change="update('payment', $event)"
      >
        <option value="">{{ t('ordersPage.filters.all') }}</option>
        <option v-for="status in PAYMENT_STATUSES" :key="status" :value="status">
          {{ t(`ordersPage.payment.${status}`) }}
        </option>
      </select>
    </label>
    <label class="filters__field">
      <span>{{ t('ordersPage.filters.fulfillment') }}</span>
      <select
        data-test="filter-fulfillment"
        :value="model.fulfillment"
        @change="update('fulfillment', $event)"
      >
        <option value="">{{ t('ordersPage.filters.all') }}</option>
        <option v-for="status in FULFILLMENT_STATUSES" :key="status" :value="status">
          {{ t(`ordersPage.fulfillment.${status}`) }}
        </option>
      </select>
    </label>
    <label class="filters__field">
      <span>{{ t('ordersPage.filters.afterSale') }}</span>
      <select
        data-test="filter-after-sale"
        :value="model.afterSale"
        @change="update('afterSale', $event)"
      >
        <option value="">{{ t('ordersPage.filters.all') }}</option>
        <option v-for="status in AFTER_SALE_STATUSES" :key="status" :value="status">
          {{ t(`ordersPage.afterSale.${status}`) }}
        </option>
      </select>
    </label>
    <button
      v-if="active"
      class="filters__clear"
      type="button"
      data-test="filters-clear"
      @click="clear"
    >
      {{ t('ordersPage.filters.clear') }}
    </button>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 14px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
}

.filters__field {
  display: grid;
  gap: 4px;
  min-width: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-soft);
}

.filters__field select {
  min-width: 140px;
  max-width: 100%;
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--raised);
  color: var(--ink);
  font-size: 13px;
  font-weight: 400;
}

.filters__clear {
  height: 32px;
  padding: 0 10px;
  border: 0;
  border-radius: 8px;
  background: none;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--accent-ink);
}

.filters__clear:hover {
  background: var(--hover);
}

@media (max-width: 820px) {
  .filters {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .filters__field select {
    width: 100%;
    min-width: 0;
  }

  .filters__clear {
    justify-self: start;
  }
}
</style>
