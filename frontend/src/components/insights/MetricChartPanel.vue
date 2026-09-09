<script setup lang="ts">
import { BarChart3 } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useEChart } from '@/composables/useEChart'
import { useLocaleStore } from '@/stores/locale'
import type { ChatAnswer } from '@/types/chat'
import {
  chartNoDataMessage,
  chartTypeLabel,
  type ChartType,
  SUPPORTED_TYPES,
  summarizeChart,
  toChartOption,
  validateChartRows,
} from '@/utils/chart'
import { formatCell } from '@/utils/format'

const { t } = useI18n()
const localeStore = useLocaleStore()

const props = defineProps<{ answer?: ChatAnswer }>()
const container = ref<HTMLElement | null>(null)
const chart = computed(() => props.answer?.chart)
const validation = computed(() => validateChartRows(chart.value, localeStore.locale))
const allowedTypes = computed(() =>
  (chart.value?.allowedTypes ?? []).filter((type): type is ChartType =>
    SUPPORTED_TYPES.includes(type as ChartType),
  ),
)
const currentType = ref<ChartType>('LINE')
const activeType = computed<ChartType>(() =>
  allowedTypes.value.includes(currentType.value)
    ? currentType.value
    : (allowedTypes.value[0] ?? 'LINE'),
)
const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
// `option` 依赖 `localeStore.locale`（经 `validation`/`toChartOption` 间接读取），
// locale 切换时这里会重新求值，`useEChart` 的 `watch([option, ...])` 随之用新
// option 调用 `setOption(..., { notMerge: true })`——不是原地改字符串，是整份
// option 对象重建。
const option = computed(() =>
  chart.value && validation.value.renderable
    ? toChartOption(chart.value, activeType.value, reducedMotion, localeStore.locale)
    : undefined,
)
const summary = computed(() =>
  chart.value && validation.value.renderable
    ? summarizeChart(chart.value, activeType.value, localeStore.locale)
    : { total: 0, sentence: validation.value.reason ?? chartNoDataMessage(localeStore.locale) },
)

useEChart(
  container,
  option,
  computed(() => validation.value.renderable),
)
</script>

<template>
  <section class="chart-panel" :aria-label="t('metricChartPanel.sectionAria')">
    <header class="chart-panel__header">
      <BarChart3 :size="15" aria-hidden="true" />
      <h2>{{ t('metricChartPanel.title') }}</h2>
    </header>

    <figure v-if="validation.renderable && chart" class="chart-panel__figure">
      <figcaption class="chart-panel__title">
        {{ chart.title ?? t('metricChartPanel.defaultChartTitle') }}
      </figcaption>
      <div
        v-if="allowedTypes.length > 1"
        class="chart-panel__types"
        data-testid="chart-type-switcher"
        :aria-label="t('metricChartPanel.typeSwitcherAria')"
      >
        <button v-for="type in allowedTypes" :key="type" type="button" @click="currentType = type">
          {{ chartTypeLabel(type, localeStore.locale) }}
        </button>
      </div>
      <div
        ref="container"
        class="chart-panel__canvas"
        data-testid="metric-chart-canvas"
        aria-hidden="true"
      ></div>
      <p class="chart-panel__summary" data-testid="chart-summary">{{ summary.sentence }}</p>
      <details>
        <summary>{{ t('metricChartPanel.viewTable') }}</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">{{ chart.dimensionKey }}</th>
              <th scope="col">{{ chart.metricKey }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in chart.data" :key="index">
              <td>{{ formatCell(row[chart.dimensionKey!], localeStore.locale) }}</td>
              <td>{{ formatCell(row[chart.metricKey!], localeStore.locale, chart.unit) }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </figure>

    <div v-else class="chart-panel__empty" data-testid="chart-empty">
      <span>{{ t('metricChartPanel.emptyTitle') }}</span>
      <p>{{ validation.reason ?? t('metricChartPanel.emptyBody') }}</p>
    </div>
  </section>
</template>

<style scoped>
.chart-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
}

.chart-panel__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
}

.chart-panel__header h2 {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-section-title);
  font-weight: var(--font-weight-emphasis);
}

.chart-panel__placeholder {
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
  padding: var(--space-3);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface-muted);
}

.chart-panel__notice {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}

.chart-panel__canvas {
  width: 100%;
  height: 220px;
}

.chart-panel__title {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
}

.chart-panel__count {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}

.chart-panel__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-2);
  color: var(--color-text-secondary);
  text-align: center;
}

.chart-panel__empty span {
  color: var(--color-text-secondary);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-emphasis);
}

.chart-panel__empty p {
  max-width: 210px;
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}
</style>
