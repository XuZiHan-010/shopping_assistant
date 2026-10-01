<script setup lang="ts">
/**
 * 首页「需要你处理」（W Task 8，设计说明 §2.2④、§3.2）。
 *
 * 聚合三个既有来源的**第一页**，经 Adapter 直接读进本组件的局部状态，**不写共享 Store**：
 * 首页若把 `PENDING_MERCHANT` 结果写进售后 Store，晚到的响应会覆盖售后页自己的列表与游标
 * （游标绑定筛选条件，换筛选后「加载更多」会得到 `INVALID_CURSOR`）。
 * - 库存告警（`fetchInventoryAlerts`）；
 * - 待商家处理的售后（`fetchAfterSales`，只取 `PENDING_MERCHANT`）；
 * - 未忽略的内容缺口信号（`fetchSignals`，前端只按 `kind`、`isIgnored` 过滤）。
 *
 * 只取第一页：来源还有下一页时，条数写成下限「N+」，溢出说明写「还有至少 N 项」或「还有更多未列出」，
 * 不把一页的条数当成总数。
 * 每个来源单独加载、单独判定失败：某一类失败只把这一类标为不可用，其余照常显示。
 * 按类别筛选，最多显示 5 行；排序只按紧急程度分档（售罄 → 售后 → 库存偏低 → 滞销 → 内容缺口），
 * 同档保持后端返回的顺序。行动按钮经 `rail.ask()` 只预填问题并打开助手栏，不发送。
 */
import { Box, MessageCircleQuestion, Sparkles, Undo2 } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RouteLocationRaw } from 'vue-router'

import { fetchAfterSales, fetchSignals } from '@/api/adapters/afterSales'
import { fetchInventoryAlerts, type InventoryAlert } from '@/api/adapters/merchantOps'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { useRailStore } from '@/stores/rail'
import type { CustomerSignal, MerchantAfterSale } from '@/types/afterSales'
import { whenIdle } from '@/utils/idle'
import { formatDate, formatMoneyCents, formatNumber } from '@/utils/localizedFormat'

type Category = 'stock' | 'after' | 'gap'
type Filter = 'all' | Category
type SourceStatus = 'loading' | 'ready' | 'error'
type Tone = 'danger' | 'warn' | 'info' | 'violet'

interface AttentionRow {
  key: string
  category: Category
  tier: number
  tone: Tone
  icon: Component
  title: string
  meta: string
  action: string
  prompt: string
}

const ROW_CAP = 5
const CATEGORIES: Category[] = ['stock', 'after', 'gap']
const FILTERS: Filter[] = ['all', ...CATEGORIES]
const CATEGORY_ROUTE: Record<Category, RouteLocationRaw> = {
  stock: { name: 'inventory' },
  after: { name: 'after-sales' },
  gap: { name: 'customer-signals' },
}

const PAGE_LIMIT = 20

const auth = useAuthStore()
const localeStore = useLocaleStore()
const rail = useRailStore()
const { t } = useI18n()

const status = ref<Record<Category, SourceStatus>>({
  stock: 'loading',
  after: 'loading',
  gap: 'loading',
})
const filter = ref<Filter>('all')
const alerts = ref<InventoryAlert[]>([])
const pendingAfterSales = ref<MerchantAfterSale[]>([])
const signals = ref<CustomerSignal[]>([])
/** 各来源是否还有下一页：有则本类条数只是下限。 */
const hasMore = ref<Record<Category, boolean>>({ stock: false, after: false, gap: false })
let cancelIdle: (() => void) | undefined
let requestVersion = 0
let started = false

async function loadStock(): Promise<void> {
  const version = requestVersion
  try {
    const page = await auth.callWithSessionRetry((sid) =>
      fetchInventoryAlerts(sid, { limit: PAGE_LIMIT }),
    )
    if (version !== requestVersion) return
    alerts.value = page.items
    hasMore.value.stock = page.hasMore
    status.value.stock = 'ready'
  } catch {
    if (version !== requestVersion) return
    status.value.stock = 'error'
  }
}

async function loadAfterSales(): Promise<void> {
  const version = requestVersion
  try {
    const page = await auth.callWithSessionRetry((sid) =>
      fetchAfterSales(sid, { state: 'PENDING_MERCHANT', limit: PAGE_LIMIT }),
    )
    if (version !== requestVersion) return
    pendingAfterSales.value = page.items
    hasMore.value.after = page.hasMore
    status.value.after = 'ready'
  } catch {
    if (version !== requestVersion) return
    status.value.after = 'error'
  }
}

async function loadSignals(): Promise<void> {
  const version = requestVersion
  try {
    const page = await auth.callWithSessionRetry((sid) =>
      fetchSignals(sid, { includeIgnored: false, limit: PAGE_LIMIT }),
    )
    if (version !== requestVersion) return
    signals.value = page.items
    hasMore.value.gap = page.hasMore
    status.value.gap = 'ready'
  } catch {
    if (version !== requestVersion) return
    status.value.gap = 'error'
  }
}

function load(): void {
  started = true
  requestVersion += 1
  status.value = { stock: 'loading', after: 'loading', gap: 'loading' }
  hasMore.value = { stock: false, after: false, gap: false }
  void loadStock()
  void loadAfterSales()
  void loadSignals()
}

onMounted(() => {
  cancelIdle = whenIdle(load)
})
watch(
  () => localeStore.locale,
  () => {
    if (started) load()
  },
)

onUnmounted(() => {
  cancelIdle?.()
  requestVersion += 1
})

const locale = computed(() => localeStore.locale)

function stockRow(alert: InventoryAlert): AttentionRow {
  const tier = { OUT_OF_STOCK: 0, LOW_STOCK: 2, SLOW_MOVING: 3 }[alert.kind]
  const tone: Tone = { OUT_OF_STOCK: 'danger', LOW_STOCK: 'warn', SLOW_MOVING: 'info' }[
    alert.kind
  ] as Tone
  const parts = [
    t(`home.attention.stock.${alert.kind}`),
    t('home.attention.stock.available', {
      count: formatNumber(alert.stockAvailable, locale.value),
    }),
  ]
  if (alert.daysOfSupply !== null) {
    parts.push(
      t('home.attention.stock.daysOfSupply', {
        days: formatNumber(alert.daysOfSupply, locale.value),
      }),
    )
  }
  parts.push(
    t('home.attention.stock.sold30d', { count: formatNumber(alert.soldLast30d, locale.value) }),
  )
  const slow = alert.kind === 'SLOW_MOVING'
  return {
    key: `stock-${alert.id}`,
    category: 'stock',
    tier,
    tone,
    icon: Box,
    title: alert.productName,
    meta: parts.join(' · '),
    action: slow ? t('home.attention.stock.slowAction') : t('home.attention.stock.restock'),
    prompt: slow
      ? t('home.attention.stock.slowPrompt', { name: alert.productName })
      : t('home.attention.stock.restockPrompt', { name: alert.productName }),
  }
}

function afterSaleRow(item: MerchantAfterSale): AttentionRow {
  const typeKey = { RETURN_REFUND: 'typeReturn', REFUND_ONLY: 'typeRefund', TICKET: 'typeTicket' }[
    item.type
  ]
  const parts = [item.buyerAlias]
  if (item.refundAmountCents !== null) {
    parts.push(
      t('home.attention.after.refund', {
        amount: formatMoneyCents(item.refundAmountCents, locale.value),
      }),
    )
  }
  parts.push(
    t('home.attention.after.due', { due: formatDate(item.firstResponseDueAt, locale.value) }),
  )
  return {
    key: `after-${item.id}`,
    category: 'after',
    tier: 1,
    tone: 'violet',
    icon: Undo2,
    title: t('home.attention.after.title', { type: t(`afterSalesView.${typeKey}`) }),
    meta: parts.join(' · '),
    action: t('home.attention.after.action'),
    prompt: t('home.attention.after.prompt', { id: item.id }),
  }
}

function gapRow(signal: CustomerSignal): AttentionRow {
  const count = formatNumber(signal.count, locale.value)
  const name = signal.productName
  return {
    key: `gap-${signal.id}`,
    category: 'gap',
    tier: 4,
    tone: 'info',
    icon: MessageCircleQuestion,
    title: name
      ? t('home.attention.gap.title', { name, count })
      : t('home.attention.gap.titleNoProduct', { count }),
    meta: t('home.attention.gap.meta', { date: formatDate(signal.signalDate, locale.value) }),
    action: t('home.attention.gap.action'),
    prompt: name
      ? t('home.attention.gap.prompt', { name })
      : t('home.attention.gap.promptNoProduct'),
  }
}

const rowsByCategory = computed<Record<Category, AttentionRow[]>>(() => ({
  stock: status.value.stock === 'ready' ? alerts.value.map(stockRow) : [],
  after:
    status.value.after === 'ready'
      ? pendingAfterSales.value
          .filter((item) => item.state === 'PENDING_MERCHANT')
          .map(afterSaleRow)
      : [],
  gap:
    status.value.gap === 'ready'
      ? signals.value
          .filter((signal) => signal.kind === 'CONTENT_GAP' && !signal.isIgnored)
          .map(gapRow)
      : [],
}))

/** 按紧急程度分档，同档保持来源顺序（`Array.prototype.sort` 稳定）。 */
const allRows = computed(() =>
  CATEGORIES.flatMap((category) => rowsByCategory.value[category]).sort((a, b) => a.tier - b.tier),
)

const filteredRows = computed(() =>
  filter.value === 'all' ? allRows.value : rowsByCategory.value[filter.value],
)
const shownRows = computed(() => filteredRows.value.slice(0, ROW_CAP))
const hiddenCount = computed(() => filteredRows.value.length - shownRows.value.length)

const visibleCategories = computed(() => (filter.value === 'all' ? CATEGORIES : [filter.value]))
const unavailableCategories = computed(() =>
  visibleCategories.value.filter((category) => status.value[category] === 'error'),
)
const loadingAny = computed(() =>
  visibleCategories.value.some((category) => status.value[category] === 'loading'),
)

/** 某一组类别里是否有来源还有下一页（只看已成功读取的来源）。 */
function moreBeyondPage(categories: Category[]): boolean {
  return categories.some(
    (category) => status.value[category] === 'ready' && hasMore.value[category],
  )
}

/** 按钮上的条数：来源还有下一页时写成下限「N+」；来源失败写「—」。 */
function countLabel(value: Filter): string {
  if (value === 'all') {
    return `${allRows.value.length}${moreBeyondPage(CATEGORIES) ? '+' : ''}`
  }
  if (status.value[value] === 'error') return '—'
  return `${rowsByCategory.value[value].length}${moreBeyondPage([value]) ? '+' : ''}`
}

const moreUnlisted = computed(() => moreBeyondPage(visibleCategories.value))
const overflowText = computed(() => {
  if (hiddenCount.value > 0) {
    return moreUnlisted.value
      ? t('home.attention.moreAtLeast', { count: hiddenCount.value })
      : t('home.attention.more', { count: hiddenCount.value })
  }
  return moreUnlisted.value ? t('home.attention.moreUnlisted') : ''
})

const overflowRoute = computed<RouteLocationRaw | null>(() =>
  filter.value === 'all' ? null : CATEGORY_ROUTE[filter.value],
)
</script>

<template>
  <section class="panel" data-test="home-attention" aria-labelledby="home-attention-title">
    <div class="panel__head">
      <h2 id="home-attention-title">{{ t('home.attention.title') }}</h2>
      <div class="seg" role="group" :aria-label="t('home.attention.filterAria')">
        <button
          v-for="option in FILTERS"
          :key="option"
          type="button"
          :data-test="`attention-filter-${option}`"
          :aria-pressed="filter === option ? 'true' : 'false'"
          @click="filter = option"
        >
          {{ t(`home.attention.filters.${option}`) }}<b>{{ countLabel(option) }}</b>
        </button>
      </div>
    </div>

    <ul class="rows">
      <li
        v-for="row in shownRows"
        :key="row.key"
        class="rows__item"
        data-test="attention-row"
        :data-category="row.category"
      >
        <span class="kind" :class="`kind--${row.tone}`" aria-hidden="true">
          <component :is="row.icon" :size="17" />
        </span>
        <div class="rows__text">
          <div class="rows__title" data-test="attention-title">{{ row.title }}</div>
          <div class="rows__meta">{{ row.meta }}</div>
        </div>
        <button type="button" class="ask" data-test="attention-ask" @click="rail.ask(row.prompt)">
          <Sparkles :size="13" aria-hidden="true" />{{ row.action }}
        </button>
      </li>
    </ul>

    <p v-if="overflowText" class="rows__overflow" data-test="attention-overflow">
      {{ overflowText }}
      <template v-if="overflowRoute">
        ·
        <RouterLink :to="overflowRoute">{{ t('home.attention.seeAll') }}</RouterLink>
      </template>
    </p>

    <p
      v-for="category in unavailableCategories"
      :key="category"
      class="rows__notice"
      role="status"
      data-test="attention-unavailable"
    >
      {{ t('home.attention.unavailable', { category: t(`home.attention.filters.${category}`) }) }}
    </p>

    <p v-if="shownRows.length === 0 && loadingAny" class="rows__empty">
      {{ t('home.attention.loading') }}
    </p>
    <p
      v-else-if="shownRows.length === 0 && unavailableCategories.length < visibleCategories.length"
      class="rows__empty"
      data-test="attention-empty"
    >
      {{ filter === 'all' ? t('home.attention.emptyAll') : t('home.attention.empty') }}
    </p>
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
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 12px;
  padding: 14px 18px 10px;
}

.panel__head h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.005em;
}

.seg {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 2px;
  max-width: 100%;
  padding: 3px;
  border-radius: 9px;
  background: var(--well);
}

.seg button {
  padding: 4px 10px;
  border: 0;
  border-radius: 7px;
  background: none;
  font-size: 12.5px;
  color: var(--ink-soft);
  white-space: nowrap;
}

.seg button b {
  margin-left: 3px;
  font-weight: 500;
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
}

.seg button[aria-pressed='true'] {
  background: var(--card);
  color: var(--ink);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

.seg button:hover:not([aria-pressed='true']) {
  color: var(--ink);
}

.rows {
  margin: 0;
  padding: 0 8px;
  list-style: none;
}

.rows__item {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 11px 10px;
  border-top: 1px solid var(--line);
}

.rows__item:first-child {
  border-top: 0;
}

.kind {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 9px;
}

.kind--danger {
  background: var(--danger-soft);
  color: var(--danger);
}

.kind--warn {
  background: var(--warn-soft);
  color: var(--warn);
}

.kind--info {
  background: var(--info-soft);
  color: var(--info);
}

.kind--violet {
  background: var(--violet-soft);
  color: var(--violet);
}

.rows__text {
  min-width: 0;
}

.rows__title {
  font-size: 14px;
  font-weight: 500;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.rows__meta {
  margin-top: 2px;
  font-size: 12.5px;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}

.ask {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 11px;
  border: 0;
  border-radius: 99px;
  background: var(--accent-soft);
  color: var(--accent-ink);
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  transition:
    background-color 150ms,
    color 150ms;
}

.ask:hover {
  background: var(--accent);
  color: var(--on-accent);
}

.rows__overflow,
.rows__notice,
.rows__empty {
  margin: 0;
  padding: 10px 18px 14px;
  font-size: 12.5px;
  color: var(--ink-soft);
}

.rows__overflow a {
  font-weight: 600;
  color: var(--ink-2);
}

.rows__notice {
  padding-top: 8px;
  color: var(--warn);
  font-weight: 600;
}

.rows__empty {
  padding: 22px 18px;
  text-align: center;
}

@media (max-width: 820px) {
  .rows__item {
    grid-template-columns: 34px minmax(0, 1fr);
  }

  .rows__item > .ask {
    grid-column: 2;
    justify-self: start;
  }
}
</style>
