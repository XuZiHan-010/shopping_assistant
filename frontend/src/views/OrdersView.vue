<script setup lang="ts">
/**
 * 订单页（W Task 9，契约 §8.12.4，PRD M1「订单」区域）：只读订单列表 + 详情抽屉。
 *
 * - 只列本店、具备 v2 交易投影的订单；顶部说明与首页「最近订单」同一句口径
 *   （`home.orders.scope`，W Task 0 步骤 3：首页订单量含历史导入订单，条数可能不同）；
 * - 三项筛选各自映射到契约查询参数；换筛选即从第一页重读，**绝不**把旧游标带到新筛选上
 *   （游标绑定筛选条件，§8.7.4）；「加载更多」遇到 INVALID_CURSOR 时从第一页重读；
 * - 请求令牌：每次整页重读递增，晚到的旧列表或旧「加载更多」响应一律丢弃；
 * - 顾客只以店铺级脱敏别名出现（R5）；本页没有任何写操作按钮。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { fetchMerchantOrders } from '@/api/adapters/merchantOrders'
import StatusPill from '@/components/layout/StatusPill.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import OrderDetailDrawer from '@/components/orders/OrderDetailDrawer.vue'
import OrderFilters from '@/components/orders/OrderFilters.vue'
import {
  afterSaleTone,
  EMPTY_ORDER_FILTERS,
  fulfillmentTone,
  paymentTone,
  type OrderFilterState,
} from '@/components/orders/orderStatus'
import { focusIfLost, useCursorList } from '@/composables/useCursorList'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import type { MerchantOrderSummary, MerchantOrdersFilter } from '@/types/merchantOrders'
import { formatDate, formatMoneyCents } from '@/utils/localizedFormat'

const PAGE_SIZE = 20

const { t } = useI18n()
const auth = useAuthStore()
const localeStore = useLocaleStore()
const locale = computed(() => localeStore.locale)

const filters = ref<OrderFilterState>({ ...EMPTY_ORDER_FILTERS })

const filtered = computed(
  () =>
    filters.value.payment !== '' ||
    filters.value.fulfillment !== '' ||
    filters.value.afterSale !== '',
)

/** 在发请求的那一刻读取当前筛选；游标、令牌与 INVALID_CURSOR 恢复都在 `useCursorList`。 */
function query(cursor: string | null): MerchantOrdersFilter {
  const current = filters.value
  return {
    cursor,
    limit: PAGE_SIZE,
    paymentStatus: current.payment || undefined,
    fulfillmentStatus: current.fulfillment || undefined,
    afterSaleStatus: current.afterSale || undefined,
  }
}

const {
  items: orders,
  status,
  moreStatus,
  hasMore,
  restarted,
  reload,
  loadMore,
} = useCursorList<MerchantOrderSummary>((cursor) => {
  const request = query(cursor)
  return auth.callWithSessionRetry((sid) => fetchMerchantOrders(sid, request))
})

// 换任何一项筛选都从第一页重读，旧游标随之作废。
watch([filters, locale], () => void reload(), { immediate: true })

// ---------- 焦点 ----------
const panel = ref<HTMLElement | null>(null)

/** 重试按钮会随错误态消失：先把焦点交给列表面板，再重读。 */
function retry(): void {
  panel.value?.focus()
  void reload()
}

// INVALID_CURSOR 恢复会清掉列表与「加载更多」按钮；焦点若因此掉到 body，交给列表面板。
watch(
  restarted,
  (value) => {
    if (value) focusIfLost(panel.value)
  },
  { flush: 'post' },
)

// ---------- 详情抽屉 ----------
const selectedOrderId = ref<string | null>(null)
let drawerTrigger: HTMLElement | null = null

function openOrder(orderId: string, event: MouseEvent): void {
  drawerTrigger = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  selectedOrderId.value = orderId
}

async function closeOrder(): Promise<void> {
  selectedOrderId.value = null
  await nextTick()
  const target = drawerTrigger
  drawerTrigger = null
  if (target?.isConnected) target.focus()
}

// ---------- 行展示 ----------
function shortId(id: string): string {
  return id.length > 10 ? `…${id.slice(-8)}` : id
}

function itemsLabel(order: MerchantOrderSummary): string {
  return order.itemCount > 1
    ? t('home.orders.moreItems', { name: order.leadItem.name, count: order.itemCount })
    : order.leadItem.name
}
</script>

<template>
  <WorkspacePage title-id="page-title-orders" :title="t('pages.orders.title')">
    <template #intro>
      <p data-test="orders-scope">{{ t('home.orders.scope') }}</p>
      <p class="orders__sub">{{ t('ordersPage.sub') }}</p>
    </template>

    <div
      ref="panel"
      class="ws-panel"
      role="region"
      tabindex="-1"
      data-test="orders-panel"
      :aria-label="t('ordersPage.caption')"
    >
      <OrderFilters v-model="filters" />

      <div class="live" role="status">
        <p v-if="restarted" class="ws-notice" data-test="orders-restarted">
          {{ t('ordersPage.restarted') }}
        </p>
      </div>

      <p v-if="status === 'loading'" class="ws-state" role="status">
        {{ t('ordersPage.loading') }}
      </p>
      <div v-else-if="status === 'error'" class="ws-state" role="alert">
        <span>{{ t('ordersPage.loadFailed') }}</span>
        <button type="button" class="ws-link" data-test="orders-retry" @click="retry">
          {{ t('ordersPage.retry') }}
        </button>
      </div>
      <p v-else-if="orders.length === 0" class="ws-state" data-test="orders-empty">
        {{ filtered ? t('ordersPage.emptyFiltered') : t('ordersPage.empty') }}
      </p>

      <template v-else>
        <table class="ws-table">
          <caption class="sr-only">
            {{
              t('ordersPage.caption')
            }}
          </caption>
          <thead>
            <tr>
              <th scope="col">{{ t('ordersPage.columns.order') }}</th>
              <th scope="col">{{ t('ordersPage.columns.buyer') }}</th>
              <th scope="col">{{ t('ordersPage.columns.items') }}</th>
              <th scope="col" class="r">{{ t('ordersPage.columns.total') }}</th>
              <th scope="col">{{ t('ordersPage.columns.status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in orders" :key="order.id" data-test="order-row">
              <td class="cell-order">
                <button
                  type="button"
                  class="order-open"
                  data-test="order-open"
                  :aria-label="t('ordersPage.openDetail', { id: order.id })"
                  @click="openOrder(order.id, $event)"
                >
                  <span class="ws-mono" translate="no">{{ shortId(order.id) }}</span>
                </button>
                <span class="ws-sub">{{ formatDate(order.createdAt, locale) }}</span>
              </td>
              <td class="cell-buyer">
                <span class="ws-alias" translate="no">{{ order.buyerAlias }}</span>
              </td>
              <td class="cell-items">{{ itemsLabel(order) }}</td>
              <td class="cell-total r">{{ formatMoneyCents(order.totalCents, locale) }}</td>
              <td class="cell-status">
                <span class="pills">
                  <StatusPill :tone="paymentTone(order.paymentStatus)">
                    {{ t(`ordersPage.payment.${order.paymentStatus}`) }}
                  </StatusPill>
                  <StatusPill
                    v-if="order.paymentStatus === 'PAID'"
                    :tone="fulfillmentTone(order.fulfillmentStatus)"
                  >
                    {{ t(`ordersPage.fulfillment.${order.fulfillmentStatus}`) }}
                  </StatusPill>
                  <StatusPill
                    v-if="order.afterSaleStatus !== 'NONE'"
                    :tone="afterSaleTone(order.afterSaleStatus)"
                  >
                    {{ t(`ordersPage.afterSale.${order.afterSaleStatus}`) }}
                  </StatusPill>
                </span>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="ws-more">
          <span class="ws-more__count">{{ t('ordersPage.shown', { count: orders.length }) }}</span>
          <span
            v-if="moreStatus === 'error'"
            class="ws-more__error"
            role="alert"
            data-test="orders-more-error"
          >
            {{ t('ordersPage.loadMoreFailed') }}
          </span>
          <button
            v-if="hasMore"
            type="button"
            class="ws-btn ws-btn--sm"
            data-test="orders-load-more"
            :disabled="moreStatus === 'loading'"
            @click="loadMore"
          >
            {{ moreStatus === 'loading' ? t('ordersPage.loadingMore') : t('ordersPage.loadMore') }}
          </button>
        </div>
      </template>
    </div>

    <OrderDetailDrawer v-if="selectedOrderId" :order-id="selectedOrderId" @close="closeOrder" />
  </WorkspacePage>
</template>

<style scoped>
/* 面板、状态行、表格、「加载更多」与 820px 卡片化的共用规则在 assets/workspace.css（ws-*）。 */
.orders__sub {
  color: var(--ink-soft);
}

.cell-order {
  white-space: nowrap;
}

.order-open {
  display: block;
  padding: 0;
  border: 0;
  background: none;
  font-weight: 600;
  color: var(--accent-ink);
  text-align: left;
}

.order-open:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.cell-items {
  min-width: 0;
  overflow-wrap: anywhere;
}

.pills {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* 820px 以下：每单两列排布（单号 | 顾客；商品 | 金额；状态占满一行）。 */
@media (max-width: 820px) {
  .cell-order {
    white-space: normal;
  }

  .cell-buyer {
    justify-self: end;
  }

  .cell-items {
    grid-column: 1;
  }

  .cell-total {
    align-self: start;
  }

  .cell-status {
    grid-column: 1 / -1;
  }
}
</style>
