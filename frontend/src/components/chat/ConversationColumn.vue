<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
import { onUnmounted, ref } from 'vue'

import { MOCK_QUICK_QUESTIONS } from '@/api/mock/scenarios'
import { useChatStore } from '@/stores/chat'

import ChatComposer from './ChatComposer.vue'
import ChatMessage from './ChatMessage.vue'

const chatStore = useChatStore()

// 重试点击过快（上一轮还没跑完就再点一次）时，retryMessage 会返回 false 而不是
// 抛异常——这里必须把「本次点击被拒绝」的信息传给用户，否则点了没反应会显得像
// UI 卡死。用一条短暂的 aria-live 提示承接，几秒后自动消失。
const retryNotice = ref('')
let retryNoticeTimer: ReturnType<typeof setTimeout> | undefined

function showRetryNotice(): void {
  retryNotice.value = '上一轮回答仍在处理中，请稍候再试。'
  clearTimeout(retryNoticeTimer)
  retryNoticeTimer = setTimeout(() => {
    retryNotice.value = ''
  }, 3000)
}

function ask(text: string): void {
  void chatStore.submitMessage(text)
}

async function retry(localId: string): Promise<void> {
  const started = await chatStore.retryMessage(localId)
  if (!started) {
    showRetryNotice()
  }
}

onUnmounted(() => clearTimeout(retryNoticeTimer))
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

      <section v-if="chatStore.isEmptyConversation" class="empty-card">
        <span>开始一段新会话</span>
        <p>输入经营问题后，这里会呈现分析过程、结论和行动建议。</p>
        <ul class="quick-questions">
          <li v-for="question in MOCK_QUICK_QUESTIONS" :key="question">
            <button type="button" data-testid="quick-question" @click="ask(question)">
              {{ question }}
            </button>
          </li>
        </ul>
      </section>

      <template v-else>
        <ChatMessage
          v-for="message in chatStore.messages"
          :key="message.localId"
          :message="message"
          @retry="retry"
          @cancel="chatStore.cancelMessage"
          @select="chatStore.selectRound"
        />
      </template>
    </div>
    <p v-if="retryNotice" class="retry-notice" role="status" aria-live="polite">
      {{ retryNotice }}
    </p>
    <ChatComposer @submit="ask" />
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

.quick-questions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-2);
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
}

.quick-questions button {
  padding: var(--space-1-5) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-size: var(--font-size-caption);
  transition: var(--transition-interactive);
}

.quick-questions button:hover {
  border-color: #cdd7fd;
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.retry-notice {
  flex: none;
  margin: 0;
  padding: var(--space-1) var(--space-3);
  color: var(--color-danger-text);
  font-size: var(--font-size-caption);
  text-align: center;
}
</style>
