<script setup lang="ts">
import { Loader, RotateCcw, Square } from '@lucide/vue'
import { computed } from 'vue'

import type { ChatMessage as ChatMessageModel } from '@/types/chat'

const props = defineProps<{ message: ChatMessageModel }>()

const emit = defineEmits<{
  retry: [localId: string]
  cancel: [localId: string]
  select: [localId: string]
}>()

const latestStage = computed(() => props.message.steps.at(-1)?.label ?? '正在准备')
const isRunning = computed(
  () => props.message.status === 'pending' || props.message.status === 'streaming',
)
</script>

<template>
  <article
    class="chat-message"
    :class="`chat-message--${message.role}`"
    data-testid="chat-message"
    @click="emit('select', message.localId)"
  >
    <div v-if="isRunning" class="chat-message__stage" role="status" aria-live="polite">
      <Loader class="chat-message__spinner" :size="14" aria-hidden="true" />
      <span data-testid="stage-label">{{ latestStage }}</span>
      <button
        type="button"
        data-testid="cancel-button"
        aria-label="停止本次回答"
        @click.stop="emit('cancel', message.localId)"
      >
        <Square :size="12" aria-hidden="true" />
        <span>停止</span>
      </button>
    </div>

    <p v-else-if="message.status === 'cancelled'" class="chat-message__notice" aria-live="polite">
      {{ message.errorMessage }}
      <button
        type="button"
        data-testid="retry-button"
        aria-label="重新回答本轮问题"
        @click.stop="emit('retry', message.localId)"
      >
        <RotateCcw :size="12" aria-hidden="true" />
        <span>重新回答</span>
      </button>
    </p>

    <p
      v-else-if="message.status === 'error'"
      class="chat-message__notice chat-message__notice--error"
      aria-live="polite"
    >
      {{ message.errorMessage }}
      <button
        type="button"
        data-testid="retry-button"
        aria-label="重试本轮问题"
        @click.stop="emit('retry', message.localId)"
      >
        <RotateCcw :size="12" aria-hidden="true" />
        <span>重试</span>
      </button>
    </p>

    <p v-else class="chat-message__text">{{ message.text }}</p>
  </article>
</template>

<style scoped>
.chat-message {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: #fff;
  box-shadow: var(--shadow-control);
}

.chat-message--user {
  border-color: #cdd7fd;
  background: var(--color-primary-soft);
}

.chat-message__text {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-body);
  line-height: 1.6;
  white-space: pre-wrap;
}

.chat-message__stage,
.chat-message__notice {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}

.chat-message__notice--error {
  color: var(--color-danger-text);
}

.chat-message__stage button,
.chat-message__notice button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-0-5) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-small);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-size: var(--font-size-caption);
}

.chat-message__spinner {
  animation: chat-message-spin 1s linear infinite;
}

@keyframes chat-message-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
