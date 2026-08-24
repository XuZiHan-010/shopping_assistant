<script setup lang="ts">
import { computed } from 'vue'

import type { NorthStarMetrics } from '@/types/analytics'

const props = defineProps<{ metrics: NorthStarMetrics }>()

const INSUFFICIENT = '样本不足'

function percent(value: number | null): string {
  return value === null ? INSUFFICIENT : `${(value * 100).toFixed(1)}%`
}

function seconds(value: number | null): string {
  return value === null ? INSUFFICIENT : `${(value / 1000).toFixed(1)} 秒`
}

/**
 * 两个准确率刻意保持独立：用户侧是反馈满意度，系统侧是 Reviewer 一次放行率，
 * 没有人为标注的正确答案时，不能将它们合成为一个失真的「准确率」。
 */
const cards = computed(() => [
  {
    key: 'adoption',
    label: '回复采纳率',
    value: percent(props.metrics.adoptionRate),
    hint: '商家点击采纳的回答占比',
  },
  {
    key: 'user-accuracy',
    label: '用户侧准确率',
    value: percent(props.metrics.userAccuracyRate),
    hint: '点赞 /（点赞 + 点踩）',
  },
  {
    key: 'system-accuracy',
    label: '系统侧准确率',
    value: percent(props.metrics.systemAccuracyRate),
    hint: 'Reviewer 一次通过率',
  },
  {
    key: 'thinking',
    label: '平均思考时长',
    value: seconds(props.metrics.avgThinkingMs),
    hint: '一轮问答从提问到成稿',
  },
  {
    key: 'hit',
    label: '问题命中率',
    value: percent(props.metrics.hitRate),
    hint: '业务提问中命中数据或知识的占比',
  },
  {
    key: 'failure',
    label: '回答失效率',
    value: percent(props.metrics.failureRate),
    hint: '降级或质量未通过的占比',
  },
])
</script>

<template>
  <ul class="north-star" aria-label="Chat BI 北极星指标">
    <li
      v-for="card in cards"
      :key="card.key"
      class="north-star__card"
      data-testid="north-star-card"
    >
      <p class="north-star__label">{{ card.label }}</p>
      <p
        class="north-star__value"
        :class="{ 'north-star__value--empty': card.value === INSUFFICIENT }"
      >
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
