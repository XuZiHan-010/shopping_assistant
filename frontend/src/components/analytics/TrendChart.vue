<script setup lang="ts">
import { computed, ref } from 'vue'

import { useEChart } from '@/composables/useEChart'
import type { ChatBiDailyPoint } from '@/types/analytics'
import type { ChartOption } from '@/utils/chart'

const props = defineProps<{ daily: ChatBiDailyPoint[] }>()

const container = ref<HTMLElement | null>(null)
const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

const option = computed<ChartOption | undefined>(() => {
  if (props.daily.length === 0) return undefined

  return {
    animation: !reducedMotion,
    tooltip: { trigger: 'axis' },
    legend: { data: ['采纳率', '命中率', '问答量'] },
    xAxis: { type: 'category', data: props.daily.map((point) => point.statDate) },
    yAxis: [
      { type: 'value', name: '比率', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
      { type: 'value', name: '问答量', minInterval: 1 },
    ] as unknown as Record<string, unknown>,
    series: [
      {
        type: 'line',
        name: '采纳率',
        data: props.daily.map((point) =>
          point.metrics.adoptionRate === null ? null : point.metrics.adoptionRate * 100,
        ),
        connectNulls: false,
      },
      {
        type: 'line',
        name: '命中率',
        data: props.daily.map((point) =>
          point.metrics.hitRate === null ? null : point.metrics.hitRate * 100,
        ),
        connectNulls: false,
      },
      {
        type: 'bar',
        name: '问答量',
        yAxisIndex: 1,
        data: props.daily.map((point) => point.answerTotal),
      },
    ],
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
      <p class="trend-chart__eyebrow">日趋势</p>
      <h2 id="trend-chart-title">采纳率、命中率与问答量</h2>
    </header>
    <div
      v-if="option"
      ref="container"
      class="trend-chart__canvas"
      aria-label="Chat BI 日趋势图"
    ></div>
    <p v-else class="trend-chart__empty">当前窗口没有日趋势数据。</p>
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
