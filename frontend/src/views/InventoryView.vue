<script setup lang="ts">
/**
 * 库存页（PRD M5 最小集；W Task 10 换成工作区版式）。只读——补货、下架、降价都经草稿审批
 * （§8.12.2 不变量 4）。
 *
 * - 上半部是库存告警：告警类型、在库、占用、可售、近 30 天销量、可售天数都逐字来自后端；
 * - 下半部是商品内容与优惠券摘要（`catalogOps` Store）：内容缺口由后端判定，页面只翻译
 *   两个已知的内容字段名（与商品页共用 `components/catalog/productContent.ts`）。
 */
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  InventoryAlertKind,
  MerchantCoupon,
  MerchantProductContent,
} from '@/api/adapters/merchantOps'
import {
  CONTENT_FIELD_KEYS,
  isKnownProductStatus,
  productStatusTone,
} from '@/components/catalog/productContent'
import type { PillTone } from '@/components/layout/pillTone'
import StatusPill from '@/components/layout/StatusPill.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import { useCatalogOpsStore } from '@/stores/catalogOps'
import { useInventoryStore } from '@/stores/inventory'
import { useLocaleStore } from '@/stores/locale'
import { formatNumber } from '@/utils/localizedFormat'

const store = useInventoryStore()
const catalog = useCatalogOpsStore()
const localeStore = useLocaleStore()
const locale = computed(() => localeStore.locale)
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

const KIND_TONE: Record<InventoryAlertKind, PillTone> = {
  OUT_OF_STOCK: 'danger',
  LOW_STOCK: 'warn',
  SLOW_MOVING: 'muted',
}

function kindLabel(kind: InventoryAlertKind): string {
  return t(KIND_LABEL_KEY[kind])
}

function productStatusLabel(value: string): string {
  return isKnownProductStatus(value) ? t(`catalogPage.status.${value}`) : value
}

function contentFieldLabel(field: string): string {
  const key = CONTENT_FIELD_KEYS[field]
  return key ? t(`catalogPage.contentField.${key}`) : field
}

function joinNames(names: string[]): string {
  return names.join(t('catalogPage.gapSeparator'))
}

function missingFields(product: MerchantProductContent): string {
  return joinNames(product.missingContentFields.map(contentFieldLabel))
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
  <WorkspacePage title-id="page-title-inventory" :title="t('inventoryView.title')">
    <template #intro>
      <p>{{ t('inventoryView.sub') }}</p>
    </template>

    <div class="ws-panel">
      <p v-if="store.loading" class="ws-state" role="status">{{ t('inventoryView.loading') }}</p>
      <p v-else-if="store.errorMessage" class="ws-state" role="alert">{{ store.errorMessage }}</p>
      <p v-else-if="!hasAlerts" class="ws-state">{{ t('inventoryView.empty') }}</p>

      <table v-else class="ws-table inventory-view__table">
        <caption class="sr-only">
          {{
            t('inventoryView.title')
          }}
        </caption>
        <thead>
          <tr>
            <th scope="col">{{ t('inventoryView.columnProduct') }}</th>
            <th scope="col">{{ t('inventoryView.columnKind') }}</th>
            <th scope="col" class="r">{{ t('inventoryView.columnOnHand') }}</th>
            <th scope="col" class="r">{{ t('inventoryView.columnReserved') }}</th>
            <th scope="col" class="r">{{ t('inventoryView.columnAvailable') }}</th>
            <th scope="col" class="r">{{ t('inventoryView.columnSold30d') }}</th>
            <th scope="col" class="r">{{ t('inventoryView.columnDaysOfSupply') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in store.items" :key="item.id">
            <td class="cell-product">
              <strong class="name">{{ item.productName }}</strong>
            </td>
            <td class="cell-kind">
              <StatusPill :tone="KIND_TONE[item.kind]">{{ kindLabel(item.kind) }}</StatusPill>
            </td>
            <td class="cell-num r" :data-label="t('inventoryView.columnOnHand')">
              {{ formatNumber(item.stockOnHand, locale) }}
            </td>
            <td class="cell-num r" :data-label="t('inventoryView.columnReserved')">
              {{ formatNumber(item.stockReserved, locale) }}
            </td>
            <td class="cell-num cell-available r" :data-label="t('inventoryView.columnAvailable')">
              {{ formatNumber(item.stockAvailable, locale) }}
            </td>
            <td class="cell-num r" :data-label="t('inventoryView.columnSold30d')">
              {{ formatNumber(item.soldLast30d, locale) }}
            </td>
            <td class="cell-num r" :data-label="t('inventoryView.columnDaysOfSupply')">
              {{
                item.daysOfSupply === null
                  ? t('inventoryView.daysOfSupplyUnknown')
                  : formatNumber(item.daysOfSupply, locale)
              }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h2 class="ws-section-title">{{ t('inventoryView.contentTitle') }}</h2>
    <p v-if="catalog.loading" class="ws-state">{{ t('inventoryView.catalogLoading') }}</p>
    <p v-else-if="catalog.errorMessage" class="ws-alert" role="alert">{{ catalog.errorMessage }}</p>
    <p v-else-if="catalog.products.length === 0" class="ws-state">
      {{ t('inventoryView.noProducts') }}
    </p>
    <ul v-else class="cards inventory-view__cards">
      <li v-for="product in catalog.products" :key="product.id" class="ws-panel card">
        <div class="card__head">
          <strong class="name">{{ product.title }}</strong>
          <StatusPill :tone="productStatusTone(product.status)">
            {{ productStatusLabel(product.status) }}
          </StatusPill>
        </div>
        <span class="ws-sub">{{ product.category }}</span>
        <span class="card__line">
          <span class="card__label">{{ t('inventoryView.columnAvailable') }}</span>
          <strong class="card__value">{{ formatNumber(product.stockAvailable, locale) }}</strong>
        </span>
        <StatusPill v-if="product.contentComplete" tone="ok">
          {{ t('inventoryView.contentComplete') }}
        </StatusPill>
        <span v-else-if="product.missingRequiredAttributes.length > 0" class="card__line card__gap">
          <span class="card__label">{{ t('inventoryView.missingAttributes') }}</span>
          <span>{{ joinNames(product.missingRequiredAttributes) }}</span>
        </span>
        <span v-if="product.missingContentFields.length > 0" class="card__line card__gap">
          <span class="card__label">{{ t('inventoryView.missingContentFields') }}</span>
          <span>{{ missingFields(product) }}</span>
        </span>
      </li>
    </ul>
    <div v-if="catalog.hasMoreProducts" class="load-more">
      <button
        type="button"
        class="ws-btn ws-btn--sm"
        :disabled="catalog.loading"
        @click="void catalog.loadMoreProducts().catch(() => undefined)"
      >
        {{ t('inventoryView.loadMore') }}
      </button>
    </div>

    <h2 class="ws-section-title">{{ t('inventoryView.couponsTitle') }}</h2>
    <p v-if="catalog.loading" class="ws-state">{{ t('inventoryView.catalogLoading') }}</p>
    <p v-else-if="catalog.errorMessage" class="ws-alert" role="alert">{{ catalog.errorMessage }}</p>
    <p v-else-if="catalog.coupons.length === 0" class="ws-state">
      {{ t('inventoryView.noCoupons') }}
    </p>
    <ul v-else class="cards inventory-view__cards">
      <li v-for="coupon in catalog.coupons" :key="coupon.id" class="ws-panel card">
        <div class="card__head">
          <strong class="name">{{ coupon.name }}</strong>
          <StatusPill :tone="coupon.currentlyActive ? 'ok' : 'muted'">
            {{
              coupon.currentlyActive
                ? t('inventoryView.couponActive')
                : t('inventoryView.couponInactive')
            }}
          </StatusPill>
        </div>
        <span class="card__offer">{{ couponOffer(coupon) }}</span>
      </li>
    </ul>
    <div v-if="catalog.hasMoreCoupons" class="load-more">
      <button
        type="button"
        class="ws-btn ws-btn--sm"
        :disabled="catalog.loading"
        @click="void catalog.loadMoreCoupons().catch(() => undefined)"
      >
        {{ t('inventoryView.loadMore') }}
      </button>
    </div>
  </WorkspacePage>
</template>

<style scoped>
.name {
  display: block;
  min-width: 0;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.cell-num {
  white-space: nowrap;
}

.cell-available {
  font-weight: 600;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 240px), 1fr));
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

/* 卡片之间用 grid 的 gap，不要 .ws-panel + .ws-panel 的纵向外边距 */
.cards > .card {
  margin-top: 0;
}

.card {
  display: grid;
  align-content: start;
  gap: 6px;
  min-width: 0;
  padding: 14px 16px;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.card__line {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 8px;
  color: var(--ink-2);
}

.card__label {
  font-size: 12px;
  color: var(--ink-soft);
}

.card__value {
  font-variant-numeric: tabular-nums;
}

.card__gap {
  padding: 6px 9px;
  border-radius: 8px;
  background: var(--warn-soft);
  color: var(--ink);
}

.card__gap .card__label {
  color: var(--warn);
  font-weight: 600;
}

.card__offer {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--accent-ink);
}

.load-more {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}

/* 820px 以下：商品名占满首行，类型胶囊在右；五个数字各自带列名排两列。 */
@media (max-width: 820px) {
  .cell-product {
    grid-column: 1;
  }

  .cell-kind {
    grid-column: 2;
    grid-row: 1;
  }

  .cell-num {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 12.5px;
  }

  .cell-num::before {
    content: attr(data-label);
    color: var(--ink-soft);
  }
}
</style>
