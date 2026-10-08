<script setup lang="ts">
/**
 * 首页净成交额趋势图（W Task 8）：本期与基期（按星期几对齐）两条折线。
 *
 * **只能经 `defineAsyncComponent` 懒加载**（宿主 `HomeMetricPanel.vue`），ECharts 随本组件
 * 进入独立 chunk，空闲且进入视口后才下载——`scripts/check-first-paint.mjs` 正向检查这一点。
 *
 * 数据点逐一取自 overview 响应的 `current_series` / `baseline_series`（R4）：这里只把
 * 整数分换成元作为坐标值，不求和、不求比例。尺寸变化由 `useEChart` 的 ResizeObserver 重绘。
 * 画布本身对读屏不可见，旁边附一张视觉隐藏的数据表。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useEChart } from '@/composables/useEChart'
import { useLocaleStore } from '@/stores/locale'
import { usePreferencesStore } from '@/stores/preferences'
import type { OverviewHeadline } from '@/types/merchantInsights'
import type { ChartOption } from '@/utils/chart'
import { formatMoneyCents } from '@/utils/localizedFormat'

const props = defineProps<{
  headline: OverviewHeadline
  currentLabel: string
  baselineLabel: string
}>()

const { t } = useI18n()
const localeStore = useLocaleStore()
const preferences = usePreferencesStore()
const container = ref<HTMLElement | null>(null)

/** ECharts 画在 canvas 上读不到 CSS 变量：取当前主题下的 token 值，缺失时退回浅色值。 */
function token(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function weekdayLabel(date: string): string {
  // 业务日期是纯日期：按 UTC 解析再按 UTC 格式化，避免浏览器时区把它挪到前一天。
  return new Intl.DateTimeFormat(localeStore.locale, {
    weekday: 'short',
    month: 'numeric',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${date}T00:00:00Z`))
}

const hasBaseline = computed(() => props.headline.baselineSeries.length > 0)

const option = computed<ChartOption>(() => {
  // 读取主题让 option 随主题切换重建（颜色来自 token）。
  void preferences.theme
  const locale = localeStore.locale
  const accent = token('--accent', '#b5502f')
  const faint = token('--ink-faint', '#9a9384')
  const line = token('--line', '#e4dccb')
  const money = (value: number) => formatMoneyCents(Math.round(value * 100), locale)
  const series: Array<Record<string, unknown>> = [
    {
      name: props.currentLabel,
      type: 'line',
      smooth: true,
      symbolSize: 6,
      lineStyle: { width: 2.5, color: accent },
      itemStyle: { color: accent },
      data: props.headline.currentSeries.map((point) => point.valueCents / 100),
    },
  ]
  if (hasBaseline.value) {
    series.push({
      name: props.baselineLabel,
      type: 'line',
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 1.5, type: 'dashed', color: faint },
      itemStyle: { color: faint },
      data: props.headline.baselineSeries.map((point) => point.valueCents / 100),
    })
  }
  return {
    animation: false,
    grid: { left: 8, right: 8, top: 12, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => money(value),
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: props.headline.currentSeries.map((point) => weekdayLabel(point.date)),
      axisLine: { lineStyle: { color: line } },
      axisTick: { show: false },
      axisLabel: { color: faint },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: line } },
      axisLabel: {
        color: faint,
        formatter: (value: number) =>
          new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(
            value,
          ),
      },
    },
    series,
    aria: { enabled: true, label: { description: t('home.metric.chartAria') } },
  } as ChartOption
})

useEChart(container, option, ref(true))

const rows = computed(() =>
  props.headline.currentSeries.map((point, index) => ({
    date: point.date,
    current: point.valueCents,
    baseline: props.headline.baselineSeries[index]?.valueCents ?? null,
  })),
)
</script>

<template>
  <figure class="trend" data-test="home-trend-chart">
    <div ref="container" class="trend__canvas" aria-hidden="true"></div>
    <table class="sr-only" data-test="trend-table">
      <caption>
        {{
          t('home.metric.chartCaption')
        }}
      </caption>
      <thead>
        <tr>
          <th scope="col">{{ t('home.metric.chartDate') }}</th>
          <th scope="col">{{ currentLabel }}</th>
          <th v-if="hasBaseline" scope="col">{{ baselineLabel }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.date">
          <th scope="row">{{ row.date }}</th>
          <td>{{ formatMoneyCents(row.current, localeStore.locale) }}</td>
          <td v-if="hasBaseline">
            {{ row.baseline === null ? '—' : formatMoneyCents(row.baseline, localeStore.locale) }}
          </td>
        </tr>
      </tbody>
    </table>
  </figure>
</template>

<style scoped>
.trend {
  margin: 0;
}

.trend__canvas {
  width: 100%;
  height: 190px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 820px) {
  .trend__canvas {
    height: 150px;
  }
}
</style>
