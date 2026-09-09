<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NorthStarMetrics } from '@/types/analytics'

const props = defineProps<{ metrics: NorthStarMetrics }>()

const { t } = useI18n()

function percent(value: number | null): string {
  return value === null ? t('northStarCards.insufficientSample') : `${(value * 100).toFixed(1)}%`
}

function seconds(value: number | null): string {
  return value === null
    ? t('northStarCards.insufficientSample')
    : t('northStarCards.secondsValue', { value: (value / 1000).toFixed(1) })
}

/**
 * 两个准确率刻意保持独立：用户侧是反馈满意度，系统侧是 Reviewer 一次放行率，
 * 没有人为标注的正确答案时，不能将它们合成为一个失真的「准确率」。
 */
const cards = computed(() => [
  {
    key: 'adoption',
    label: t('northStarCards.adoptionLabel'),
    value: percent(props.metrics.adoptionRate),
    hint: t('northStarCards.adoptionHint'),
    empty: props.metrics.adoptionRate === null,
  },
  {
    key: 'user-accuracy',
    label: t('northStarCards.userAccuracyLabel'),
    value: percent(props.metrics.userAccuracyRate),
    hint: t('northStarCards.userAccuracyHint'),
    empty: props.metrics.userAccuracyRate === null,
  },
  {
    key: 'system-accuracy',
    label: t('northStarCards.systemAccuracyLabel'),
    value: percent(props.metrics.systemAccuracyRate),
    hint: t('northStarCards.systemAccuracyHint'),
    empty: props.metrics.systemAccuracyRate === null,
  },
  {
    key: 'thinking',
    label: t('northStarCards.thinkingLabel'),
    value: seconds(props.metrics.avgThinkingMs),
    hint: t('northStarCards.thinkingHint'),
    empty: props.metrics.avgThinkingMs === null,
  },
  {
    key: 'hit',
    label: t('northStarCards.hitLabel'),
    value: percent(props.metrics.hitRate),
    hint: t('northStarCards.hitHint'),
    empty: props.metrics.hitRate === null,
  },
  {
    key: 'failure',
    label: t('northStarCards.failureLabel'),
    value: percent(props.metrics.failureRate),
    hint: t('northStarCards.failureHint'),
    empty: props.metrics.failureRate === null,
  },
])
</script>

<template>
  <ul class="north-star" :aria-label="t('northStarCards.sectionAria')">
    <li
      v-for="card in cards"
      :key="card.key"
      class="north-star__card"
      data-testid="north-star-card"
    >
      <p class="north-star__label">{{ card.label }}</p>
      <p class="north-star__value" :class="{ 'north-star__value--empty': card.empty }">
        {{ card.value }}
      </p>
      <p class="north-star__hint">{{ card.hint }}</p>
    </li>
  </ul>
</template>

<style scoped>
.north-star {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10.75rem, 1fr));
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.north-star__card {
  min-height: 9.5rem;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-top: 3px solid var(--color-teal);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
}

.north-star__label,
.north-star__hint,
.north-star__value {
  margin: 0;
}

.north-star__label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-title);
  letter-spacing: 0.06em;
}

.north-star__value {
  margin: var(--space-3) 0 var(--space-2);
  color: var(--color-text);
  font-size: 1.8rem;
  font-weight: var(--font-weight-title);
  line-height: 1;
}

.north-star__value--empty {
  color: var(--color-text-muted);
  font-size: var(--font-size-section-title);
  line-height: 1.8rem;
}

.north-star__hint {
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}
</style>
