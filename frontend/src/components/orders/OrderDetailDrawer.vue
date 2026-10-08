<script setup lang="ts">
/**
 * 订单详情抽屉（W Task 9，契约 §8.12.4 `GET /api/v2/merchant/orders/{order_id}`）。
 *
 * - 只读：价格快照、三个状态维度、支付与关闭时间；没有任何写操作（发货、改价、关闭都不经本组）；
 * - 顾客只以店铺级脱敏别名出现，界面上不存在 buyer_key（R5）；
 * - 模态对话框：打开时焦点移进面板，Tab 困在面板内，Esc / 遮罩 / 关闭按钮发出 `close`；
 *   Esc 会 `preventDefault()`，外壳据此不再连带收起助手栏。焦点交还给触发行由父组件负责；
 * - 请求令牌：`orderId` 变化或卸载后，旧订单的慢响应一律丢弃，不会覆盖当前订单。
 */
import { X } from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { fetchMerchantOrder } from '@/api/adapters/merchantOrders'
import StatusPill from '@/components/layout/StatusPill.vue'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import type { MerchantOrderDetail } from '@/types/merchantOrders'
import { formatDate, formatMoneyCents } from '@/utils/localizedFormat'

import { afterSaleTone, fulfillmentTone, paymentTone } from './orderStatus'

const props = defineProps<{ orderId: string }>()
const emit = defineEmits<{ close: [] }>()

const TITLE_ID = 'order-drawer-title'

const { t } = useI18n()
const auth = useAuthStore()
const localeStore = useLocaleStore()
const locale = computed(() => localeStore.locale)

const detail = ref<MerchantOrderDetail | null>(null)
const status = ref<'loading' | 'ready' | 'error'>('loading')
const panel = ref<HTMLElement | null>(null)
let requestToken = 0

async function load(): Promise<void> {
  const token = ++requestToken
  const orderId = props.orderId
  status.value = 'loading'
  detail.value = null
  try {
    const result = await auth.callWithSessionRetry((sid) => fetchMerchantOrder(sid, orderId))
    if (token !== requestToken) return
    detail.value = result
    status.value = 'ready'
  } catch {
    if (token !== requestToken) return
    status.value = 'error'
  }
}

/** 重试按钮会随错误态消失：焦点先交给对话框面板（仍在模态框内），再重读。 */
function retry(): void {
  panel.value?.focus()
  void load()
}

watch([() => props.orderId, locale], () => void load(), { immediate: true })

function money(cents: number): string {
  return formatMoneyCents(cents, locale.value)
}

/** 优惠以负数展示；为 0 时显示 ¥0.00，不出现「-¥0.00」。 */
function discount(cents: number): string {
  return cents > 0 ? money(-cents) : money(0)
}

function date(value: string): string {
  return formatDate(value, locale.value)
}

const FOCUSABLE = 'a[href], button:not([disabled]), select, input, textarea, [tabindex="0"]'

function focusables(): HTMLElement[] {
  return Array.from(panel.value?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const items = focusables()
  if (items.length === 0) {
    event.preventDefault()
    panel.value.focus()
    return
  }
  const first = items[0]!
  const last = items[items.length - 1]!
  const active = document.activeElement
  const inside = active instanceof HTMLElement && panel.value.contains(active)
  if (event.shiftKey && (!inside || active === first || active === panel.value)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (!inside || active === last)) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  void nextTick(() => panel.value?.focus())
})

onBeforeUnmount(() => {
  requestToken += 1
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="drawer">
    <div
      class="drawer__backdrop"
      data-test="drawer-backdrop"
      aria-hidden="true"
      @click="emit('close')"
    ></div>
    <section
      ref="panel"
      class="drawer__panel"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="TITLE_ID"
      tabindex="-1"
    >
      <header class="drawer__head">
        <div class="drawer__heading">
          <h2 :id="TITLE_ID">{{ t('orderDrawer.title') }}</h2>
          <p class="drawer__id">
            <span class="sr-only">{{ t('orderDrawer.orderId') }}</span>
            <span class="mono" translate="no">{{ orderId }}</span>
          </p>
        </div>
        <button
          class="drawer__close"
          type="button"
          data-test="drawer-close"
          :aria-label="t('orderDrawer.close')"
          @click="emit('close')"
        >
          <X :size="18" aria-hidden="true" />
        </button>
      </header>

      <div class="drawer__body">
        <p v-if="status === 'loading'" class="drawer__state" role="status">
          {{ t('orderDrawer.loading') }}
        </p>
        <div v-else-if="status === 'error'" class="drawer__state" role="alert">
          <span>{{ t('orderDrawer.loadFailed') }}</span>
          <button type="button" class="link-button" data-test="drawer-retry" @click="retry">
            {{ t('orderDrawer.retry') }}
          </button>
        </div>

        <template v-else-if="detail">
          <dl class="facts">
            <div class="facts__row">
              <dt>{{ t('orderDrawer.buyer') }}</dt>
              <dd data-test="buyer-alias">
                <span class="alias" translate="no">{{ detail.buyerAlias }}</span>
              </dd>
            </div>
            <div class="facts__row">
              <dt>{{ t('orderDrawer.createdAt') }}</dt>
              <dd>{{ date(detail.createdAt) }}</dd>
            </div>
            <div v-if="detail.paymentStatus === 'PENDING'" class="facts__row" data-test="pay-by">
              <dt>{{ t('orderDrawer.payBy') }}</dt>
              <dd>{{ date(detail.payBy) }}</dd>
            </div>
            <div v-if="detail.paidAt" class="facts__row">
              <dt>{{ t('orderDrawer.paidAt') }}</dt>
              <dd>{{ date(detail.paidAt) }}</dd>
            </div>
            <div v-if="detail.closedAt" class="facts__row">
              <dt>{{ t('orderDrawer.closedAt') }}</dt>
              <dd>{{ date(detail.closedAt) }}</dd>
            </div>
            <div v-if="detail.closeReason" class="facts__row">
              <dt>{{ t('orderDrawer.closeReasonLabel') }}</dt>
              <dd>{{ t(`orderDrawer.closeReason.${detail.closeReason}`) }}</dd>
            </div>
            <div class="facts__row">
              <dt>{{ t('orderDrawer.lastEventAt') }}</dt>
              <dd>{{ date(detail.lastEventAt) }}</dd>
            </div>
          </dl>

          <section class="block" aria-labelledby="order-drawer-status">
            <h3 id="order-drawer-status">{{ t('orderDrawer.statusTitle') }}</h3>
            <dl class="statuses">
              <div class="statuses__row" data-test="status-payment">
                <dt>{{ t('orderDrawer.status.payment') }}</dt>
                <dd>
                  <StatusPill :tone="paymentTone(detail.paymentStatus)">
                    {{ t(`ordersPage.payment.${detail.paymentStatus}`) }}
                  </StatusPill>
                </dd>
              </div>
              <div class="statuses__row" data-test="status-fulfillment">
                <dt>{{ t('orderDrawer.status.fulfillment') }}</dt>
                <dd>
                  <StatusPill :tone="fulfillmentTone(detail.fulfillmentStatus)">
                    {{ t(`ordersPage.fulfillment.${detail.fulfillmentStatus}`) }}
                  </StatusPill>
                </dd>
              </div>
              <div class="statuses__row" data-test="status-after-sale">
                <dt>{{ t('orderDrawer.status.afterSale') }}</dt>
                <dd>
                  <StatusPill :tone="afterSaleTone(detail.afterSaleStatus)">
                    {{ t(`ordersPage.afterSale.${detail.afterSaleStatus}`) }}
                  </StatusPill>
                </dd>
              </div>
            </dl>
          </section>

          <section class="block" aria-labelledby="order-drawer-snapshot">
            <h3 id="order-drawer-snapshot">{{ t('orderDrawer.snapshotTitle') }}</h3>
            <p class="block__note">{{ t('orderDrawer.snapshotNote') }}</p>
            <ul class="lines">
              <li
                v-for="line in detail.items"
                :key="line.orderItemId"
                class="line"
                data-test="snapshot-line"
              >
                <div class="line__main">
                  <strong class="line__name">{{ line.name }}</strong>
                  <span class="line__calc">
                    <span>{{ t('orderDrawer.columns.quantity') }} {{ line.quantity }}</span>
                    <span
                      >{{ t('orderDrawer.columns.unitPrice') }}
                      {{ money(line.unitPriceCents) }}</span
                    >
                    <span v-if="line.discountCents > 0">
                      {{ t('orderDrawer.columns.discount') }} {{ discount(line.discountCents) }}
                    </span>
                  </span>
                </div>
                <span class="line__total">
                  <span class="sr-only">{{ t('orderDrawer.columns.lineTotal') }}</span>
                  {{ money(line.lineTotalCents) }}
                </span>
              </li>
            </ul>
            <dl class="totals">
              <div class="totals__row" data-test="snapshot-subtotal">
                <dt>{{ t('orderDrawer.subtotal') }}</dt>
                <dd>{{ money(detail.subtotalCents) }}</dd>
              </div>
              <div class="totals__row" data-test="snapshot-discount">
                <dt>{{ t('orderDrawer.discount') }}</dt>
                <dd>{{ discount(detail.discountCents) }}</dd>
              </div>
              <div v-if="detail.couponId" class="totals__row">
                <dt>{{ t('orderDrawer.coupon') }}</dt>
                <dd class="mono" translate="no">{{ detail.couponId }}</dd>
              </div>
              <div class="totals__row totals__row--total" data-test="snapshot-total">
                <dt>{{ t('orderDrawer.total') }}</dt>
                <dd>{{ money(detail.totalCents) }}</dd>
              </div>
            </dl>
          </section>

          <p class="drawer__readonly">{{ t('orderDrawer.readOnly') }}</p>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.drawer__backdrop {
  position: fixed;
  inset: 0;
  z-index: 85;
  background: rgba(10, 16, 13, 0.4);
}

.drawer__panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 90;
  display: flex;
  flex-direction: column;
  width: min(440px, 100vw);
  max-width: 100vw;
  background: var(--card);
  border-left: 1px solid var(--line);
  box-shadow: var(--shadow-lg);
  color: var(--ink);
}

.drawer__panel:focus {
  outline: none;
}

.drawer__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--line);
}

.drawer__heading {
  min-width: 0;
}

.drawer__head h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 19px;
  font-weight: 600;
}

.drawer__id {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}

.drawer__close {
  display: inline-grid;
  flex-shrink: 0;
  place-items: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: none;
  color: var(--ink-2);
}

.drawer__close:hover {
  background: var(--hover);
  color: var(--ink);
}

.drawer__body {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 16px 20px 24px;
}

.drawer__state {
  margin: 0;
  font-size: 13px;
  color: var(--ink-soft);
}

.link-button {
  margin-left: 8px;
  padding: 0;
  border: 0;
  background: none;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--accent-ink);
}

.link-button:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.mono {
  font-family: var(--font-mono);
}

.alias {
  padding: 1px 6px;
  border-radius: 6px;
  background: var(--well);
  color: var(--ink-2);
  font-family: var(--font-mono);
  font-size: 12px;
}

.facts,
.statuses,
.totals {
  margin: 0;
}

.facts__row,
.statuses__row,
.totals__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  font-size: 13px;
}

.facts__row dt,
.statuses__row dt,
.totals__row dt {
  color: var(--ink-soft);
}

.facts__row dd,
.statuses__row dd,
.totals__row dd {
  min-width: 0;
  margin: 0;
  text-align: right;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}

.block {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.block h3 {
  margin: 0 0 6px;
  font-size: 14px;
  font-weight: 600;
}

.block__note {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--ink-soft);
}

.lines {
  margin: 0;
  padding: 0;
  list-style: none;
}

.line {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
}

.line__main {
  min-width: 0;
}

.line__name {
  display: block;
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.line__calc {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-soft);
  font-variant-numeric: tabular-nums;
}

.line__total {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.totals {
  margin-top: 6px;
}

.totals__row--total {
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
  font-weight: 600;
}

.totals__row--total dt {
  color: var(--ink);
}

.drawer__readonly {
  margin: 18px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-soft);
}
</style>
