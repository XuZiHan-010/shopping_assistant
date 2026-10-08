<script setup lang="ts">
/**
 * 首页主指标面板（W Task 8，设计说明 §2.2③，契约 §8.12.4）：只突出净成交额。
 *
 * - 左：大数字、相对上周同期的变化、趋势图；右：变化来自哪里（类目归因前 5 项 + 其余合计）；
 *   底部：已登记的三项辅助指标（订单量、退款金额、退货率），点击即问助手原因。
 * - **所有数字、比例、贡献只来自 overview 响应**（R4）：组件只做单位与语言格式化，
 *   不据序列求和、不算比例或贡献；辅助指标为 null 时写「暂无数据」，不写成 0。
 * - 降级（R7）：`degraded` 为真时显示原因、不画趋势图；归因 `STOPPED` 时显示停止原因、不列类目。
 *   来源、数据截至时间与口径版本如实标注；订单量口径与「最近订单」不同，写明差异。
 * - 首屏：取数推迟到空闲之后；趋势图经 `defineAsyncComponent` 懒加载，
 *   `useIdleVisible` 为真（空闲且进入视口）才挂载（`scripts/check-first-paint.mjs` 正向检查）。
 */
import { Sparkles } from '@lucide/vue'
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { fetchMerchantMetricsOverview } from '@/api/adapters/merchantInsights'
import { useIdleVisible } from '@/composables/useIdleVisible'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { useRailStore } from '@/stores/rail'
import type { MerchantMetricsOverview, OverviewSecondaryMetric } from '@/types/merchantInsights'
import { whenIdle } from '@/utils/idle'
import { formatDate, formatMoneyCents, formatNumber, formatRatioBp } from '@/utils/localizedFormat'

const HomeTrendChart = defineAsyncComponent(() => import('./HomeTrendChart.vue'))

/** 契约上限就是 5 项；多于 5 项时也只列前 5 项，其余由 `remaining_*` 说明（M3）。 */
const MAX_SEGMENTS = 5

const auth = useAuthStore()
const localeStore = useLocaleStore()
const rail = useRailStore()
const { t } = useI18n()

const overview = ref<MerchantMetricsOverview | undefined>(undefined)
/** 首帧即为 true：空闲前、首次取数中都显示加载态。 */
const loading = ref(true)
const failed = ref(false)
const chartHost = ref<HTMLElement | null>(null)
const chartReady = useIdleVisible(chartHost)
let cancelIdle: (() => void) | undefined
let started = false
/**
 * 请求令牌：每次取数递增，只有最新一次的结果能写入。语言切换时旧请求可能晚到，
 * 靠它丢弃，而不是跳过新请求。
 */
let requestSeq = 0

/**
 * 取数；已有数据时重新取数**不清空**上一份结果（趋势图不重新挂载），只标记「正在更新」；
 * 失败时保留上一份数据并另给出失败说明与重试。
 */
async function load(): Promise<void> {
  started = true
  const seq = ++requestSeq
  loading.value = true
  failed.value = false
  try {
    const result = await auth.callWithSessionRetry((sid) => fetchMerchantMetricsOverview(sid))
    if (seq === requestSeq) overview.value = result
  } catch {
    if (seq === requestSeq) failed.value = true
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

onMounted(() => {
  cancelIdle = whenIdle(() => void load())
})

// 周期说明等由后端按展示语言渲染：切换语言后重新取数（首次取数仍等空闲；
// 在途的旧语言请求由请求令牌丢弃）。
watch(
  () => localeStore.locale,
  () => {
    if (started) void load()
  },
)

onUnmounted(() => cancelIdle?.())

const locale = computed(() => localeStore.locale)
const headline = computed(() => overview.value?.headline)
const attribution = computed(() => overview.value?.attribution)
const segments = computed(() => attribution.value?.segments.slice(0, MAX_SEGMENTS) ?? [])
const stopped = computed(() => attribution.value?.mode === 'STOPPED')
const showChart = computed(() => overview.value !== undefined && !overview.value.degraded)

const changeText = computed(() =>
  formatRatioBp(headline.value?.changeRatioBp ?? null, locale.value, { signed: true }),
)
const changeTone = computed(() => ((headline.value?.changeRatioBp ?? 0) >= 0 ? 'good' : 'bad'))

const baselineText = computed(() => {
  const value = overview.value
  if (!value) return ''
  const period = value.baselinePeriod.label
  return value.headline.baselineCents === null
    ? t('home.metric.baselineNone', { period })
    : `${t('home.metric.versus', { period })} ${formatMoneyCents(value.headline.baselineCents, locale.value)}`
})

/** 后端按 `abs(contribution)` 降序给出，第一项就是变化最大的类目；这里只取用，不排序。 */
const topSegment = computed(() => segments.value[0])

function askWhy(): void {
  const value = overview.value
  if (!value) return
  rail.ask(
    t('home.metric.askWhyPrompt', {
      period: value.currentPeriod.label,
      baseline: value.baselinePeriod.label,
    }),
  )
}

function formatSecondary(metric: OverviewSecondaryMetric, value: number | null): string {
  if (value === null) return t('home.metric.noData')
  if (metric.unit === 'CENTS') return formatMoneyCents(value, locale.value)
  if (metric.unit === 'RATIO_BP')
    return formatRatioBp(value, locale.value) ?? t('home.metric.noData')
  return formatNumber(value, locale.value)
}

function askSecondary(metric: OverviewSecondaryMetric): void {
  const value = overview.value
  if (!value) return
  rail.ask(
    t(`home.metric.secondaryPrompt.${metric.metricCode}`, { period: value.currentPeriod.label }),
  )
}

const metaText = computed(() => {
  const value = overview.value
  if (!value) return ''
  const sources = value.analysisSources
    .map((entry) => t(`home.metric.analysisSource.${entry.source}`))
    .join('、')
  return t('home.metric.meta', {
    sources,
    source: t(`home.metric.dataSource.${value.source}`),
    asOf: formatDate(value.dataAsOf, locale.value),
    version: value.definitionVersion,
  })
})
</script>

<template>
  <section
    class="metric"
    data-test="home-metric"
    :aria-label="t('home.metric.title')"
    :aria-busy="loading ? 'true' : 'false'"
  >
    <div v-if="!overview && loading" class="metric__status">{{ t('home.metric.loading') }}</div>
    <div v-else-if="!overview || !headline" class="metric__status" role="alert">
      <span>{{ t('home.metric.loadFailed') }}</span>
      <button type="button" class="link-ask" data-test="metric-retry" @click="load">
        {{ t('home.metric.retry') }}
      </button>
    </div>

    <template v-else>
      <div v-if="failed" class="metric__status metric__status--inline" role="alert">
        <span>{{ t('home.metric.loadFailed') }}</span>
        <button type="button" class="link-ask" data-test="metric-retry" @click="load">
          {{ t('home.metric.retry') }}
        </button>
      </div>
      <div class="metric__main">
        <div class="metric__label">
          <h2 class="metric__title">
            {{ t('home.metric.title') }}
            <span data-test="metric-period">· {{ overview.currentPeriod.label }}</span>
            <span
              v-if="loading"
              class="metric__refreshing"
              role="status"
              data-test="metric-refreshing"
            >
              {{ t('home.metric.refreshing') }}
            </span>
          </h2>
          <span v-if="showChart" class="legend" aria-hidden="true">
            <span><i></i>{{ t('home.metric.legendCurrent') }}</span>
            <span v-if="headline.baselineSeries.length > 0">
              <i class="legend__prior"></i>{{ t('home.metric.legendBaseline') }}
            </span>
          </span>
        </div>
        <div class="metric__value">
          <strong data-test="metric-value">{{
            formatMoneyCents(headline.currentCents, locale)
          }}</strong>
          <span
            v-if="changeText"
            class="chg"
            :class="`chg--${changeTone}`"
            data-test="metric-change"
          >
            {{ changeText }}
          </span>
          <span class="metric__cmp" data-test="metric-baseline">{{ baselineText }}</span>
        </div>

        <p
          v-if="overview.degraded"
          class="metric__degraded"
          role="status"
          data-test="metric-degraded"
        >
          {{
            overview.degradedReason
              ? t('home.metric.degraded', { reason: overview.degradedReason })
              : t('home.metric.degradedNoReason')
          }}
        </p>
        <div
          v-else
          ref="chartHost"
          class="metric__chart"
          :aria-label="t('home.metric.chartAria')"
          role="group"
        >
          <HomeTrendChart
            v-if="chartReady"
            :headline="headline"
            :current-label="t('home.metric.legendCurrent')"
            :baseline-label="t('home.metric.legendBaseline')"
          />
          <p v-else class="metric__chart-pending">{{ t('home.metric.chartPending') }}</p>
        </div>
      </div>

      <div class="metric__side">
        <h3>{{ t('home.metric.where') }}</h3>
        <p v-if="stopped" class="metric__stopped" role="status" data-test="attribution-stopped">
          {{ attribution?.stoppedReason }}
        </p>
        <template v-else>
          <ul class="bars">
            <li
              v-for="segment in segments"
              :key="segment.name"
              class="bar-row"
              data-test="attribution-row"
            >
              <span class="bar-row__name">{{ segment.name }}</span>
              <span v-if="segment.shareBp !== null" class="bar-row__share">
                {{ t('home.metric.share', { share: formatRatioBp(segment.shareBp, locale) }) }}
              </span>
              <span
                class="bar-row__value"
                :class="segment.contributionCents < 0 ? 'is-neg' : 'is-pos'"
              >
                {{ formatMoneyCents(segment.contributionCents, locale, { signed: true }) }}
              </span>
            </li>
            <li
              v-if="attribution && attribution.remainingCount > 0"
              class="bar-row bar-row--rest"
              data-test="attribution-remaining"
            >
              <span class="bar-row__name">{{
                t('home.metric.remaining', { count: attribution.remainingCount })
              }}</span>
              <span class="bar-row__value">
                {{
                  formatMoneyCents(attribution.remainingContributionCents, locale, { signed: true })
                }}
              </span>
            </li>
          </ul>
          <p v-if="topSegment" class="metric__why" data-test="attribution-why">
            {{
              t('home.metric.why', {
                name: topSegment.name,
                amount: formatMoneyCents(topSegment.contributionCents, locale, { signed: true }),
              })
            }}
            <button type="button" class="link-ask" data-test="attribution-ask" @click="askWhy">
              <Sparkles :size="13" aria-hidden="true" />{{ t('home.metric.askWhy') }}
            </button>
          </p>
        </template>
      </div>

      <div class="metric__foot">
        <button
          v-for="metric in overview.secondary"
          :key="metric.metricCode"
          type="button"
          class="mini"
          data-test="secondary-metric"
          :aria-label="
            t('home.metric.secondaryAria', {
              label: t(`home.metric.secondary.${metric.metricCode}`),
              value: formatSecondary(metric, metric.currentValue),
              baseline: formatSecondary(metric, metric.baselineValue),
            })
          "
          @click="askSecondary(metric)"
        >
          <span class="mini__label">{{ t(`home.metric.secondary.${metric.metricCode}`) }}</span>
          <strong class="mini__value" data-test="secondary-current">
            {{ formatSecondary(metric, metric.currentValue) }}
          </strong>
          <span class="mini__base" data-test="secondary-baseline">
            {{
              t('home.metric.secondaryBaseline', {
                value: formatSecondary(metric, metric.baselineValue),
              })
            }}
          </span>
          <span class="mini__hint" aria-hidden="true">{{ t('home.metric.secondaryAskHint') }}</span>
        </button>
      </div>

      <div class="metric__notes">
        <p data-test="metric-meta">{{ metaText }}</p>
        <p data-test="metric-order-scope">{{ t('home.metric.orderScope') }}</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
/* 主指标：净成交额的大数字 + 趋势（左），变化来自哪里（右），其余指标缩成底部一行（原型 .metric）。 */
.metric {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
  box-shadow: var(--shadow-sm);
}

.metric__status {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 22px 20px;
  font-size: 14px;
  color: var(--ink-2);
}

.metric__status--inline {
  padding: 10px 20px;
  border-bottom: 1px solid var(--line);
  color: var(--warn);
  font-weight: 600;
}

.metric__refreshing {
  margin-left: 6px;
  font-weight: 400;
  color: var(--ink-faint);
}

.metric__main {
  min-width: 0;
  padding: 16px 20px 10px;
}

.metric__side {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 16px 20px 12px;
  border-left: 1px solid var(--line);
}

.metric__label {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 4px 10px;
  font-size: 13px;
  color: var(--ink-soft);
}

.metric__title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-soft);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 12px;
  color: var(--ink-soft);
}

.legend i {
  display: inline-block;
  width: 14px;
  height: 2px;
  margin-right: 5px;
  vertical-align: middle;
  background: var(--accent);
}

.legend .legend__prior {
  background: repeating-linear-gradient(90deg, var(--ink-faint) 0 4px, transparent 4px 7px);
}

.metric__value {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
  margin: 4px 0 2px;
}

.metric__value strong {
  font-family: var(--font-display);
  font-size: 40px;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.05;
  font-variant-numeric: tabular-nums lining-nums;
  overflow-wrap: anywhere;
}

.metric__cmp {
  font-size: 12.5px;
  color: var(--ink-faint);
}

.chg {
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.chg--good {
  background: var(--ok-soft);
  color: var(--ok);
}

.chg--bad {
  background: var(--danger-soft);
  color: var(--danger);
}

.metric__chart {
  min-height: 190px;
  margin-top: 6px;
}

.metric__chart-pending {
  display: grid;
  place-items: center;
  height: 190px;
  margin: 0;
  border-radius: 10px;
  background: var(--well);
  font-size: 12.5px;
  color: var(--ink-faint);
}

.metric__degraded,
.metric__stopped {
  margin: 10px 0 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 13px;
  font-weight: 600;
}

.metric__side h3 {
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-soft);
}

.bars {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.bar-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 8px;
  align-items: baseline;
  font-size: 13px;
}

.bar-row__name {
  min-width: 0;
  overflow-wrap: anywhere;
}

.bar-row__share {
  font-size: 12px;
  color: var(--ink-soft);
}

.bar-row__value {
  font-weight: 600;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.bar-row__value.is-neg {
  color: var(--danger);
}

.bar-row__value.is-pos {
  color: var(--ok);
}

.bar-row--rest {
  color: var(--ink-soft);
}

.metric__why {
  margin: auto 0 0;
  padding-top: 12px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink-2);
}

.link-ask {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: none;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--accent-ink);
}

.link-ask:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.metric__foot {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-top: 1px solid var(--line);
}

.mini {
  all: unset;
  box-sizing: border-box;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  min-width: 0;
  padding: 12px 20px;
  border-left: 1px solid var(--line);
  cursor: pointer;
  transition: background-color 150ms;
}

.mini:first-child {
  border-left: 0;
}

.mini:hover {
  background: var(--hover);
}

.mini:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.mini__label,
.mini__base {
  font-size: 12.5px;
  color: var(--ink-soft);
}

.mini__value {
  font-family: var(--font-display);
  font-size: 19px;
  font-weight: 600;
  font-variant-numeric: tabular-nums lining-nums;
}

.mini__hint {
  margin-left: auto;
  font-size: 12px;
  color: var(--accent-ink);
  opacity: 0;
  transition: opacity 150ms;
}

.mini:hover .mini__hint,
.mini:focus-visible .mini__hint {
  opacity: 1;
}

.metric__notes {
  grid-column: 1 / -1;
  padding: 8px 20px 12px;
  border-top: 1px solid var(--line);
}

.metric__notes p {
  margin: 2px 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-soft);
}

@media (max-width: 960px) {
  .metric {
    grid-template-columns: minmax(0, 1fr);
  }

  .metric__side {
    border-left: 0;
    border-top: 1px solid var(--line);
  }
}

@media (max-width: 820px) {
  .metric__main,
  .metric__side {
    padding: 14px 14px 10px;
  }

  .metric__value strong {
    font-size: 32px;
  }

  .metric__chart,
  .metric__chart-pending {
    min-height: 150px;
    height: auto;
  }

  .metric__chart-pending {
    height: 150px;
  }

  .metric__foot {
    grid-template-columns: minmax(0, 1fr);
  }

  .mini {
    padding: 10px 14px;
    border-left: 0;
    border-top: 1px solid var(--line);
  }

  .mini:first-child {
    border-top: 0;
  }

  .metric__notes {
    padding: 8px 14px 12px;
  }
}
</style>
