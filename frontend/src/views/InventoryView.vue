<script setup lang="ts">
/** 库存告警视图（PRD M5 最小集）。只读——补货、下架、降价都经草稿审批（§8.12.2 不变量 4）。 */
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import type { InventoryAlertKind, MerchantCoupon } from '@/api/adapters/merchantOps'
import { useCatalogOpsStore } from '@/stores/catalogOps'
import { useInventoryStore } from '@/stores/inventory'

const store = useInventoryStore()
const catalog = useCatalogOpsStore()
const { t } = useI18n()

onMounted(() => {
  void store.loadAlerts()
  void catalog.load().catch(() => undefined)
})

const KIND_LABEL_KEY: Record<InventoryAlertKind, string> = {
  OUT_OF_STOCK: 'inventoryView.kindOutOfStock',
  LOW_STOCK: 'inventoryView.kindLowStock',
  SLOW_MOVING: 'inventoryView.kindSlowMoving',
}

function kindLabel(kind: InventoryAlertKind): string {
  return t(KIND_LABEL_KEY[kind])
}

function couponOffer(coupon: MerchantCoupon): string {
  if (coupon.kind === 'PERCENT_OFF' && coupon.discountBps !== null) {
    return t('inventoryView.percentOffer', { percent: (10000 - coupon.discountBps) / 100 })
  }
  if (coupon.kind === 'AMOUNT_OFF' && coupon.amountOffCents !== null) {
    return t('inventoryView.amountOffer', {
      threshold: (coupon.minSpendCents / 100).toFixed(2),
      amount: (coupon.amountOffCents / 100).toFixed(2),
    })
  }
  return coupon.kind === 'PERCENT_OFF'
    ? t('inventoryView.percentCoupon')
    : t('inventoryView.amountCoupon')
}

const hasAlerts = computed(() => store.items.length > 0)
</script>

<template>
  <section class="inventory-view">
    <h1>{{ t('inventoryView.title') }}</h1>

    <p v-if="store.loading">{{ t('inventoryView.loading') }}</p>
    <p v-else-if="store.errorMessage" role="alert">{{ store.errorMessage }}</p>
    <p v-else-if="!hasAlerts">{{ t('inventoryView.empty') }}</p>

    <table v-else class="inventory-view__table">
      <thead>
        <tr>
          <th>{{ t('inventoryView.columnProduct') }}</th>
          <th>{{ t('inventoryView.columnKind') }}</th>
          <th>{{ t('inventoryView.columnOnHand') }}</th>
          <th>{{ t('inventoryView.columnReserved') }}</th>
          <th>{{ t('inventoryView.columnAvailable') }}</th>
          <th>{{ t('inventoryView.columnSold30d') }}</th>
          <th>{{ t('inventoryView.columnDaysOfSupply') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in store.items" :key="item.id">
          <td>{{ item.productName }}</td>
          <td>{{ kindLabel(item.kind) }}</td>
          <td>{{ item.stockOnHand }}</td>
          <td>{{ item.stockReserved }}</td>
          <td>{{ item.stockAvailable }}</td>
          <td>{{ item.soldLast30d }}</td>
          <td>
            {{
              item.daysOfSupply === null
                ? t('inventoryView.daysOfSupplyUnknown')
                : item.daysOfSupply
            }}
          </td>
        </tr>
      </tbody>
    </table>
  </section>
  <section class="inventory-view">
    <h2>{{ t('inventoryView.contentTitle') }}</h2>
    <p v-if="catalog.loading">{{ t('inventoryView.catalogLoading') }}</p>
    <p v-else-if="catalog.errorMessage" role="alert">{{ catalog.errorMessage }}</p>
    <p v-else-if="catalog.products.length === 0">{{ t('inventoryView.noProducts') }}</p>
    <ul v-else class="inventory-view__cards">
      <li v-for="product in catalog.products" :key="product.id">
        <strong>{{ product.title }}</strong>
        <span>{{ product.category }} · {{ product.status }}</span>
        <span>{{ t('inventoryView.columnAvailable') }}：{{ product.stockAvailable }}</span>
        <span v-if="product.contentComplete">{{ t('inventoryView.contentComplete') }}</span>
        <span v-else-if="product.missingRequiredAttributes.length > 0">{{ t('inventoryView.missingAttributes') }}：{{ product.missingRequiredAttributes.join('、') }}</span>
        <span v-if="product.missingContentFields.length > 0">{{ t('inventoryView.missingContentFields') }}：{{ product.missingContentFields.join('、') }}</span>
      </li>
    </ul>
    <button v-if="catalog.hasMoreProducts" type="button" :disabled="catalog.loading" @click="void catalog.loadMoreProducts().catch(() => undefined)">
      {{ t('inventoryView.loadMore') }}
    </button>

    <h2>{{ t('inventoryView.couponsTitle') }}</h2>
    <p v-if="catalog.loading">{{ t('inventoryView.catalogLoading') }}</p>
    <p v-else-if="catalog.errorMessage" role="alert">{{ catalog.errorMessage }}</p>
    <p v-else-if="catalog.coupons.length === 0">{{ t('inventoryView.noCoupons') }}</p>
    <ul v-else class="inventory-view__cards">
      <li v-for="coupon in catalog.coupons" :key="coupon.id">
        <strong>{{ coupon.name }}</strong>
        <span>{{ coupon.currentlyActive ? t('inventoryView.couponActive') : t('inventoryView.couponInactive') }}</span>
        <span>{{ couponOffer(coupon) }}</span>
      </li>
    </ul>
    <button v-if="catalog.hasMoreCoupons" type="button" :disabled="catalog.loading" @click="void catalog.loadMoreCoupons().catch(() => undefined)">
      {{ t('inventoryView.loadMore') }}
    </button>
  </section>
</template>

<style scoped>
.inventory-view__cards {
  display: grid;
  gap: 0.75rem;
  list-style: none;
  padding: 0;
}
.inventory-view__cards li {
  display: grid;
  gap: 0.25rem;
  min-width: 0;
  overflow-wrap: anywhere;
  padding: 0.75rem;
  border: 1px solid var(--border-color, #ddd);
  border-radius: 0.5rem;
}
</style>
