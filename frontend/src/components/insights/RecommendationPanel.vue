<script setup lang="ts">
import { Lightbulb, MessageCircleQuestion } from '@lucide/vue'
import { computed } from 'vue'

import type { ChatAnswer } from '@/types/chat'

const props = defineProps<{ answer?: ChatAnswer }>()

const emit = defineEmits<{
  ask: [question: string]
}>()

const recommendations = computed(() => props.answer?.recommendations ?? [])
const suggestedQuestions = computed(() => props.answer?.suggestions.current ?? [])
</script>

<template>
  <section class="recommendation-panel" aria-label="行动建议">
    <div v-if="!answer" class="recommendation-panel__empty" data-testid="recommendation-empty">
      <span>暂无行动建议</span>
      <p>基于经营数据的建议和后续问题会显示在这里。</p>
    </div>

    <template v-else>
      <header class="recommendation-panel__header">
        <Lightbulb :size="15" aria-hidden="true" />
        <h2>行动建议</h2>
      </header>

      <ul v-if="recommendations.length > 0" class="recommendation-panel__list">
        <li
          v-for="(recommendation, index) in recommendations"
          :key="index"
          class="recommendation-panel__item"
        >
          <p class="recommendation-panel__title">{{ recommendation.title }}</p>
          <p class="recommendation-panel__evidence">依据：{{ recommendation.evidence }}</p>
          <p class="recommendation-panel__action">建议：{{ recommendation.action }}</p>
        </li>
      </ul>
      <p v-else class="recommendation-panel__notice">本轮回答暂无可执行的行动建议。</p>

      <div class="recommendation-panel__suggestions">
        <header class="recommendation-panel__header">
          <MessageCircleQuestion :size="15" aria-hidden="true" />
          <h2>猜你想问</h2>
        </header>

        <ul v-if="suggestedQuestions.length > 0" class="recommendation-panel__question-list">
          <li v-for="question in suggestedQuestions" :key="question">
            <button
              type="button"
              class="recommendation-panel__question"
              data-testid="suggested-question"
              @click="emit('ask', question)"
            >
              {{ question }}
            </button>
          </li>
        </ul>
        <p v-else class="recommendation-panel__notice">暂无推荐追问问题。</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.recommendation-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
}

.recommendation-panel__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
}

.recommendation-panel__header h2 {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-section-title);
  font-weight: var(--font-weight-emphasis);
}

.recommendation-panel__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2-5);
  margin: 0;
  padding: 0;
  list-style: none;
}

.recommendation-panel__item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-muted);
}

.recommendation-panel__title {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
}

.recommendation-panel__evidence,
.recommendation-panel__action {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}

.recommendation-panel__suggestions {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border);
}

.recommendation-panel__question-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
  margin: 0;
  padding: 0;
  list-style: none;
}

.recommendation-panel__question {
  width: 100%;
  padding: var(--space-2) var(--space-2-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-primary-strong);
  background: var(--color-primary-soft);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  text-align: left;
  transition: var(--transition-interactive);
}

.recommendation-panel__question:hover {
  border-color: #cdd7fd;
  background: #e3e9ff;
}

.recommendation-panel__notice {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}

.recommendation-panel__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-2);
  color: var(--color-text-secondary);
  text-align: center;
}

.recommendation-panel__empty span {
  color: var(--color-text-secondary);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-emphasis);
}

.recommendation-panel__empty p {
  max-width: 210px;
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}
</style>
