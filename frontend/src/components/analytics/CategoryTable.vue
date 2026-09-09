<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { ChatBiCategoryRow } from '@/types/analytics'

defineProps<{ rows: ChatBiCategoryRow[] }>()

const { t } = useI18n()

function percent(value: number | null): string {
  return value === null ? t('categoryTable.insufficientSample') : `${(value * 100).toFixed(1)}%`
}

function seconds(value: number | null): string {
  return value === null
    ? t('categoryTable.insufficientSample')
    : t('categoryTable.secondsValue', { value: (value / 1000).toFixed(1) })
}
</script>

<template>
  <section class="category-table" aria-labelledby="category-table-title">
    <header>
      <p class="category-table__eyebrow">{{ t('categoryTable.eyebrow') }}</p>
      <h2 id="category-table-title">{{ t('categoryTable.title') }}</h2>
    </header>
    <div class="category-table__scroll">
      <table>
        <thead>
          <tr>
            <th scope="col">{{ t('categoryTable.colCategory') }}</th>
            <th scope="col">{{ t('categoryTable.colAnswerTotal') }}</th>
            <th scope="col">{{ t('categoryTable.colAdoption') }}</th>
            <th scope="col">{{ t('categoryTable.colUserAccuracy') }}</th>
            <th scope="col">{{ t('categoryTable.colSystemAccuracy') }}</th>
            <th scope="col">{{ t('categoryTable.colThinking') }}</th>
            <th scope="col">{{ t('categoryTable.colHit') }}</th>
            <th scope="col">{{ t('categoryTable.colFailure') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.category">
            <th scope="row">{{ row.displayName }}</th>
            <td>{{ row.answerTotal }}</td>
            <td>{{ percent(row.metrics.adoptionRate) }}</td>
            <td>{{ percent(row.metrics.userAccuracyRate) }}</td>
            <td>{{ percent(row.metrics.systemAccuracyRate) }}</td>
            <td>{{ seconds(row.metrics.avgThinkingMs) }}</td>
            <td>{{ percent(row.metrics.hitRate) }}</td>
            <td>{{ percent(row.metrics.failureRate) }}</td>
          </tr>
          <tr v-if="rows.length === 0">
            <td colspan="8" class="category-table__empty">{{ t('categoryTable.empty') }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.category-table {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
}

.category-table header,
.category-table h2,
.category-table p {
  margin: 0;
}

.category-table__eyebrow {
  color: var(--color-teal);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-title);
  letter-spacing: 0.1em;
}

.category-table h2 {
  margin-top: var(--space-1);
  font-size: var(--font-size-section-title);
}

.category-table__scroll {
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-small);
}

table {
  width: 100%;
  min-width: 55rem;
  border-collapse: collapse;
  white-space: nowrap;
  font-size: var(--font-size-caption);
}

th,
td {
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
  text-align: left;
}

thead th {
  border-top: 0;
  color: var(--color-text-secondary);
  background: var(--color-surface-muted);
  font-weight: var(--font-weight-title);
}

tbody th {
  color: var(--color-text);
  font-weight: var(--font-weight-emphasis);
}

.category-table__empty {
  color: var(--color-text-secondary);
  text-align: center;
}
</style>
