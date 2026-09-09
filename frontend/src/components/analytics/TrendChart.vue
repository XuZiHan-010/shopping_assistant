<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useEChart } from '@/composables/useEChart'
import { useLocaleStore } from '@/stores/locale'
import type { ChatBiDailyPoint } from '@/types/analytics'
import type { ChartOption } from '@/utils/chart'
import { formatNumber } from '@/utils/localizedFormat'

const props = defineProps<{ daily: ChatBiDailyPoint[] }>()

const { t } = useI18n()
const localeStore = useLocaleStore()
const container = ref<HTMLElement | null>(null)
const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

// 依赖 `localeStore.locale`（经 `t()` 间接读取）——locale 切换时这个 computed
// 重新求值，`useEChart` 的 `watch([option, ...])` 因此拿到一份全新的 option
// 对象（而不是原地改字符串），触发 `setOption(..., { notMerge: true })`。
const option = computed<ChartOption | undefined>(() => {
  if (props.daily.length === 0) return undefined

  const locale = localeStore.locale
  const legendAdoption = t('trendChart.legendAdoption')
  const legendHit = t('trendChart.legendHit')
  const legendAnswers = t('trendChart.legendAnswers')

  return {
    animation: !reducedMotion,
    // 不在 ECharts option 里额外设置 `title`——标题已经由下方 DOM 的
    // `<h2 id="trend-chart-title">` 承担并正确随 locale 切换，画布内再叠加
    // 一份原生 title 会造成同一句话渲染两次。这里刻意与
    // `MetricChartPanel.vue`（只用 DOM `<figcaption>`，不设置 option.title）
    // 保持一致。
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number | string) =>
        typeof value === 'number' ? formatNumber(value, locale) : value,
    },
    legend: { data: [legendAdoption, legendHit, legendAnswers] },
    // 原始日期字符串（`statDate`）原样透传，不按 locale 重新格式化。
    xAxis: { type: 'category', data: props.daily.map((point) => point.statDate) },
    yAxis: [
      {
        type: 'value',
        name: t('trendChart.axisRate'),
        min: 0,
        max: 100,
        // 百分号是中英文共用的记号，不随 locale 改写。
        axisLabel: { formatter: '{value}%' },
      },
      {
        type: 'value',
        name: t('trendChart.axisAnswers'),
        minInterval: 1,
        axisLabel: { formatter: (value: number) => formatNumber(value, locale) },
      },
    ] as unknown as Record<string, unknown>,
    series: [
      {
        type: 'line',
        name: legendAdoption,
        data: props.daily.map((point) =>
          point.metrics.adoptionRate === null ? null : point.metrics.adoptionRate * 100,
        ),
        connectNulls: false,
      },
      {
        type: 'line',
        name: legendHit,
        data: props.daily.map((point) =>
          point.metrics.hitRate === null ? null : point.metrics.hitRate * 100,
        ),
        connectNulls: false,
      },
      {
        type: 'bar',
        name: legendAnswers,
        yAxisIndex: 1,
        data: props.daily.map((point) => point.answerTotal),
      },
    ],
    aria: { enabled: true, label: { description: t('trendChart.ariaDescription') } },
  }
})

useEChart(
  container,
  option,
  computed(() => option.value !== undefined),
)
</script>

<template>
  <section class="trend-chart" aria-labelledby="trend-chart-title">
    <header>
      <p class="trend-chart__eyebrow">{{ t('trendChart.eyebrow') }}</p>
      <h2 id="trend-chart-title">{{ t('trendChart.title') }}</h2>
    </header>
    <div
      v-if="option"
      ref="container"
      class="trend-chart__canvas"
      :aria-label="t('trendChart.canvasAria')"
    ></div>
    <p v-else class="trend-chart__empty">{{ t('trendChart.empty') }}</p>
  </section>
</template>

<style scoped>
.trend-chart {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
}

.trend-chart header,
.trend-chart h2,
.trend-chart p {
  margin: 0;
}

.trend-chart__eyebrow {
  color: var(--color-teal);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-title);
  letter-spacing: 0.1em;
}

.trend-chart h2 {
  margin-top: var(--space-1);
  font-size: var(--font-size-section-title);
}

.trend-chart__canvas {
  width: 100%;
  height: 19rem;
}

.trend-chart__empty {
  padding: var(--space-5) 0;
  color: var(--color-text-secondary);
  text-align: center;
}
</style>
