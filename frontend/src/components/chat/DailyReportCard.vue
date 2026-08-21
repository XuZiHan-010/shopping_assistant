<script setup lang="ts">
import { Check, CircleAlert, ClipboardCheck } from '@lucide/vue'

import type { DailyReport } from '@/types/report'

defineProps<{
  report?: DailyReport
  pending?: boolean
  adopted?: boolean
}>()

const emit = defineEmits<{ adopt: [] }>()
</script>

<template>
  <section v-if="report" class="daily-report" aria-label="每日经营日报">
    <header class="daily-report__header">
      <ClipboardCheck :size="17" aria-hidden="true" />
      <h2>每日经营日报</h2>
      <time :datetime="report.reportDate">{{ report.reportDate }}</time>
    </header>

    <p v-if="report.degraded" class="daily-report__degraded">
      <CircleAlert :size="15" aria-hidden="true" />
      {{ report.degradedReason }}
    </p>

    <dl v-else class="daily-report__metrics">
      <div v-for="metric in report.metrics" :key="metric.code">
        <dt>{{ metric.displayName }}</dt>
        <dd>
          {{ metric.value }}<small>{{ metric.unit }}</small>
        </dd>
      </div>
    </dl>

    <ol class="daily-report__suggestions">
      <li v-for="suggestion in report.suggestions" :key="suggestion">{{ suggestion }}</li>
    </ol>
    <button
      type="button"
      class="daily-report__adopt"
      :disabled="pending || adopted"
      @click="emit('adopt')"
    >
      <Check :size="16" aria-hidden="true" />
      <span>{{ adopted ? '已采纳本期建议' : '采纳本期建议' }}</span>
    </button>
  </section>
</template>

<style scoped>
.daily-report {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
}
.daily-report__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-primary-strong);
}
.daily-report__header h2 {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-section-title);
}
.daily-report__header time {
  margin-left: auto;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}
.daily-report__metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
  margin: 0;
}
.daily-report__metrics div {
  min-width: 0;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-muted);
}
.daily-report__metrics dt {
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}
.daily-report__metrics dd {
  margin: var(--space-1) 0 0;
  color: var(--color-text);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-emphasis);
}
.daily-report__metrics small {
  margin-left: 2px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-regular);
}
.daily-report__suggestions {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding-left: 18px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}
.daily-report__degraded {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: 0;
  color: var(--color-danger);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}
.daily-report__adopt {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: var(--control-height);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-primary-strong);
  background: var(--color-primary-soft);
  font-size: var(--font-size-control);
}
.daily-report__adopt:disabled {
  cursor: default;
  opacity: 0.65;
}
</style>
