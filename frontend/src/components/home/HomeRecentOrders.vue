<script setup lang="ts">
/**
 * 首页「最近订单」（W Task 8，契约 §8.12.4）：订单列表前 3 条，只读。
 *
 * 订单只读面只列本店、具备 v2 交易投影的订单；首页主指标的订单量含历史导入订单，
 * 两者条数可能不同——区块内如实说明（W Task 0 步骤 3 的口径）。顾客只以店铺级
 * 脱敏别名出现（R5）。状态文案只由三个状态维度映射，不推断「物流停滞」一类履约模型里没有的状态；
 * 映射与文案与订单页共用（`orders/orderStatus.ts` 的 `recentOrderStatus`、`StatusPill`）。
 */
import { ArrowRight } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { fetchMerchantOrders } from '@/api/adapters/merchantOrders'
import StatusPill from '@/components/layout/StatusPill.vue'
import { recentOrderStatus } from '@/components/orders/orderStatus'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import type { MerchantOrderSummary } from '@/types/merchantOrders'
import { whenIdle } from '@/utils/idle'
import { formatDate, formatMoneyCents } from '@/utils/localizedFormat'

const RECENT_LIMIT = 3

const auth = useAuthStore()
const localeStore = useLocaleStore()
const { t } = useI18n()

const orders = ref<MerchantOrderSummary[]>([])
const status = ref<'loading' | 'ready' | 'error'>('loading')
let cancelIdle: (() => void) | undefined
let requestVersion = 0
let started = false

async function load(): Promise<void> {
  started = true
  const version = ++requestVersion
  orders.value = []
  status.value = 'loading'
  try {
    const page = await auth.callWithSessionRetry((sid) =>
      fetchMerchantOrders(sid, { limit: RECENT_LIMIT }),
    )
    if (version !== requestVersion) return
    orders.value = page.items.slice(0, RECENT_LIMIT)
    status.value = 'ready'
  } catch {
    if (version !== requestVersion) return
    status.value = 'error'
  }
}

onMounted(() => {
  cancelIdle = whenIdle(() => void load())
})

watch(
  () => localeStore.locale,
  () => {
    if (started) void load()
  },
)

onUnmounted(() => {
  cancelIdle?.()
  requestVersion += 1
})

const locale = computed(() => localeStore.locale)

function itemsLabel(order: MerchantOrderSummary): string {
  return order.itemCount > 1
    ? t('home.orders.moreItems', { name: order.leadItem.name, count: order.itemCount })
    : order.leadItem.name
}
</script>

<template>
  <section class="panel" data-test="home-recent-orders" aria-labelledby="home-recent-title">
    <div class="panel__head">
      <h2 id="home-recent-title">{{ t('home.orders.title') }}</h2>
      <RouterLink class="panel__more" data-test="recent-orders-all" :to="{ name: 'orders' }">
        {{ t('home.orders.all') }}<ArrowRight :size="13" aria-hidden="true" />
      </RouterLink>
    </div>
    <p class="panel__scope" data-test="recent-orders-scope">{{ t('home.orders.scope') }}</p>

    <p v-if="status === 'loading'" class="orders__status">{{ t('home.orders.loading') }}</p>
    <div v-else-if="status === 'error'" class="orders__status" role="alert">
      <span>{{ t('home.orders.loadFailed') }}</span>
      <button type="button" class="orders__retry" data-test="recent-orders-retry" @click="load">
        {{ t('home.orders.retry') }}
      </button>
    </div>
    <p v-else-if="orders.length === 0" class="orders__status" data-test="recent-orders-empty">
      {{ t('home.orders.empty') }}
    </p>
    <ul v-else class="orders">
      <li v-for="order in orders" :key="order.id" class="orders__item" data-test="recent-order">
        <div class="orders__text">
          <strong class="orders__name">{{ itemsLabel(order) }}</strong>
          <span class="orders__meta">
            <span class="alias">{{ order.buyerAlias }}</span>
            {{ formatDate(order.createdAt, locale) }} ·
            {{ formatMoneyCents(order.totalCents, locale) }}
          </span>
        </div>
        <StatusPill :tone="recentOrderStatus(order).tone">
          {{ t(recentOrderStatus(order).messageKey) }}
        </StatusPill>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.panel {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
  box-shadow: var(--shadow-sm);
}

.panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px 4px;
}

.panel__head h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.005em;
}

.panel__more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
  text-decoration: none;
  white-space: nowrap;
}

.panel__more:hover {
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.panel__scope {
  margin: 0;
  padding: 0 18px 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-soft);
}

.orders {
  margin: 0;
  padding: 0 0 6px;
  list-style: none;
}

.orders__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 18px;
  border-top: 1px solid var(--line);
}

.orders__text {
  min-width: 0;
}

.orders__name {
  display: block;
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.orders__meta {
  display: block;
  font-size: 12px;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}

.alias {
  margin-right: 4px;
  padding: 1px 6px;
  border-radius: 6px;
  background: var(--well);
  color: var(--ink-2);
  font-family: var(--font-mono);
  font-size: 12px;
}

.orders__status {
  margin: 0;
  padding: 18px;
  font-size: 13px;
  color: var(--ink-soft);
}

.orders__retry {
  margin-left: 8px;
  padding: 0;
  border: 0;
  background: none;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--accent-ink);
}

.orders__retry:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}
</style>
