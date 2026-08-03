<script setup lang="ts">
import { BarChart3 } from '@lucide/vue'
import { computed } from 'vue'

import type { ChatAnswer } from '@/types/chat'

const props = defineProps<{ answer?: ChatAnswer }>()

const chart = computed(() => props.answer?.chart)
const isEnabled = computed(() => chart.value?.enabled === true)
const pointCount = computed(() => chart.value?.data.length ?? 0)
</script>

<template>
  <section class="chart-panel" aria-label="指标图表">
    <header class="chart-panel__header">
      <BarChart3 :size="15" aria-hidden="true" />
      <h2>指标图表</h2>
    </header>

    <div v-if="isEnabled" class="chart-panel__placeholder" data-testid="chart-placeholder">
      <p class="chart-panel__notice">图表将在 F4 呈现，当前仅展示占位说明。</p>
      <p v-if="chart?.title" class="chart-panel__title">{{ chart.title }}</p>
      <p class="chart-panel__count">共 {{ pointCount }} 个数据点</p>
    </div>

    <div v-else class="chart-panel__empty" data-testid="chart-empty">
      <span>暂无图表</span>
      <p>发起可视化类问题后，这里会显示图表的占位说明。</p>
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

.chart-panel__title {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
}

.chart-panel__count {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
}

.chart-panel__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-2);
  color: var(--color-text-muted);
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
