<script setup lang="ts">
import { Sparkles } from '@lucide/vue'

import ChatComposer from './ChatComposer.vue'

const emit = defineEmits<{
  submit: [message: string]
}>()
</script>

<template>
  <main class="conversation-column" aria-label="商家助手对话" data-testid="conversation-column">
    <div class="conversation-column__list" data-testid="chat-list">
      <section class="welcome-card">
        <div class="welcome-card__icon"><Sparkles :size="19" aria-hidden="true" /></div>
        <div>
          <h2>您好，我是您的经营助手</h2>
          <p>可以查询经营指标、查看业务明细，也可以结合数据给出分析与建议。</p>
        </div>
      </section>
      <section class="empty-card">
        <span>开始一段新会话</span>
        <p>输入经营问题后，这里会呈现分析过程、结论和行动建议。</p>
      </section>
    </div>
    <ChatComposer @submit="emit('submit', $event)" />
  </main>
</template>

<style scoped>
.conversation-column {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(217, 225, 237, 0.95);
  border-radius: var(--radius-column);
  background: rgba(250, 252, 255, 0.86);
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(18px);
}

.conversation-column__list {
  min-height: 0;
  flex: 1;
  display: grid;
  align-content: start;
  gap: var(--space-3);
  overflow: auto;
  padding: var(--space-3);
}

.welcome-card,
.empty-card {
  border: 1px solid var(--color-border);
  box-shadow: 0 7px 24px rgba(37, 52, 82, 0.055);
}

.welcome-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-card);
  background: linear-gradient(115deg, rgba(238, 242, 255, 0.96), rgba(246, 251, 255, 0.96));
}

.welcome-card__icon {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: var(--color-primary);
  background: #fff;
  box-shadow: 0 5px 14px rgba(79, 110, 247, 0.12);
}

.welcome-card h2 {
  margin: 0;
  font-size: var(--font-size-section-title);
}

.welcome-card p,
.empty-card p {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-control);
  line-height: var(--line-height-body);
}

.empty-card {
  min-height: 160px;
  display: grid;
  place-content: center;
  padding: var(--space-5);
  border-style: dashed;
  border-radius: 11px;
  color: var(--color-text-muted);
  background: rgba(255, 255, 255, 0.58);
  text-align: center;
}

.empty-card span {
  color: var(--color-text-secondary);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-emphasis);
}
</style>
