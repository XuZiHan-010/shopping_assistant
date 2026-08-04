<script setup lang="ts">
export interface RoundEntry {
  /** 助手消息的 localId——选中轮次用的就是它（chatStore.selectRound）。 */
  localId: string
  /** 本轮的用户提问，用作目录条目的可读标题。 */
  question: string
}

defineProps<{
  rounds: readonly RoundEntry[]
  selectedId?: string
}>()

defineEmits<{
  select: [localId: string]
}>()
</script>

<template>
  <nav class="conversation-nav" aria-label="本次会话的轮次目录">
    <ol class="conversation-nav__list">
      <li v-for="(round, index) in rounds" :key="round.localId">
        <button
          class="conversation-nav__item"
          type="button"
          data-testid="conversation-nav-item"
          :aria-current="round.localId === selectedId ? 'true' : undefined"
          @click="$emit('select', round.localId)"
        >
          <span class="conversation-nav__index" aria-hidden="true">{{ index + 1 }}</span>
          <span class="conversation-nav__text">{{ round.question }}</span>
        </button>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.conversation-nav {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: rgba(255, 255, 255, 0.72);
}

.conversation-nav__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1-5);
  margin: 0;
  padding: 0;
  list-style: none;
}

.conversation-nav__item {
  max-width: 200px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1) var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-small);
  color: var(--color-text-secondary);
  background: transparent;
  font-size: var(--font-size-caption);
  transition: var(--transition-colors);
}

.conversation-nav__item:hover,
.conversation-nav__item[aria-current='true'] {
  border-color: #cdd7fd;
  color: var(--color-primary-strong);
  background: var(--color-primary-soft);
}

.conversation-nav__index {
  width: 16px;
  height: 16px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: var(--color-primary);
  font-size: 10px;
  font-weight: var(--font-weight-control);
}

.conversation-nav__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
