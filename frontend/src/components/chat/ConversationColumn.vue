<script setup lang="ts">
import { Sparkles } from '@lucide/vue'
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

import { MOCK_QUICK_QUESTIONS } from '@/api/mock/scenarios'
import { useChatStore } from '@/stores/chat'

import ChatComposer from './ChatComposer.vue'
import ChatMessage from './ChatMessage.vue'
import ConversationNav from './ConversationNav.vue'

const chatStore = useChatStore()

// 目录条目要显示的是「问题」，可选中的却是「助手轮次」——两者是相邻的一对消息
// （submitMessage 成对入列）。在这里把这层配对一次性摊平，目录组件只管渲染。
const rounds = computed(() =>
  chatStore.messages.flatMap((message, index) =>
    message.role === 'assistant'
      ? [{ localId: message.localId, question: chatStore.messages[index - 1]?.text ?? '本轮提问' }]
      : [],
  ),
)

/**
 * 自动滚到底，但不跟用户抢滚动条。
 *
 * 判据是「用户此刻是不是贴着底部」：贴着就跟着新内容走，往上翻看历史就一直不动，
 * 直到用户自己滚回底部为止。流式回答每来一个 step 都会长高，若无条件 scrollTop
 * 到底，用户想回看上一轮时会被反复弹回去。
 */
const BOTTOM_THRESHOLD_PX = 48
const listElement = ref<HTMLElement | null>(null)
const stickToBottom = ref(true)

function handleListScroll(): void {
  const element = listElement.value
  if (!element) return

  const distanceToBottom = element.scrollHeight - element.scrollTop - element.clientHeight
  stickToBottom.value = distanceToBottom <= BOTTOM_THRESHOLD_PX
}

watch(
  // deep：不只是新增消息，流式过程中同一条消息的 steps 与 text 也在长。
  () => chatStore.messages,
  async () => {
    if (!stickToBottom.value) return

    await nextTick()
    const element = listElement.value
    if (element) element.scrollTop = element.scrollHeight
  },
  { deep: true },
)

// 重试点击过快（上一轮还没跑完就再点一次）时，retryMessage 会返回 false 而不是
// 抛异常——这里必须把「本次点击被拒绝」的信息传给用户，否则点了没反应会显得像
// UI 卡死。用一条短暂的 aria-live 提示承接，几秒后自动消失。
const retryNotice = ref('')
let retryNoticeTimer: ReturnType<typeof setTimeout> | undefined

function showRetryNotice(text = '上一轮回答仍在处理中，请稍候再试。'): void {
  retryNotice.value = text
  clearTimeout(retryNoticeTimer)
  retryNoticeTimer = setTimeout(() => {
    retryNotice.value = ''
  }, 3000)
}

async function ask(text: string): Promise<void> {
  // submitMessage 在上一轮还在途时返回 false。和重试一样，被拒必须让用户看到，
  // 否则点了没反应像是界面卡死。
  const started = await chatStore.submitMessage(text)
  if (!started && text.trim()) showRetryNotice()
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
    <!-- 只有一轮时目录没有导航价值，反而占掉对话区高度。 -->
    <ConversationNav
      v-if="rounds.length >= 2"
      class="conversation-column__nav"
      :rounds="rounds"
      :selected-id="chatStore.selectedRoundId"
      @select="chatStore.selectRound"
    />
    <div
      ref="listElement"
      class="conversation-column__list"
      data-testid="chat-list"
      @scroll="handleListScroll"
    >
      <section class="welcome-card">
        <div class="welcome-card__icon"><Sparkles :size="19" aria-hidden="true" /></div>
        <div>
          <h2>您好，我是您的经营助手</h2>
          <p>可以查询经营指标、查看业务明细，也可以结合数据给出分析与建议。</p>
        </div>
      </section>

      <section v-if="chatStore.isEmptyConversation" class="empty-card">
        <span class="empty-card__eyebrow">快速体验</span>
        <strong>点一个问题，看看助手能做什么</strong>
        <ul class="quick-questions">
          <li v-for="item in MOCK_QUICK_QUESTIONS" :key="item.question">
            <!-- data-question 让测试拿到「问题本身」，不用从含分类眉标的按钮全文里剥。 -->
            <button
              type="button"
              data-testid="quick-question"
              :data-question="item.question"
              @click="ask(item.question)"
            >
              <span class="quick-questions__category">{{ item.category }}</span>
              {{ item.question }}
            </button>
          </li>
        </ul>
      </section>

      <template v-else>
        <ChatMessage
          v-for="message in chatStore.messages"
          :key="message.localId"
          :message="message"
          :selected="message.localId === chatStore.selectedRoundId"
          @retry="retry"
          @cancel="chatStore.cancelMessage"
          @select="chatStore.selectRound"
        />
      </template>
    </div>
    <p v-if="retryNotice" class="retry-notice" role="status" aria-live="polite">
      {{ retryNotice }}
    </p>
    <ChatComposer :busy="chatStore.isBusy" @submit="ask" />
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

.conversation-column__nav {
  flex: none;
  margin: var(--space-3) var(--space-3) 0;
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
  display: grid;
  padding: var(--space-4);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.58);
}

.empty-card__eyebrow {
  color: var(--color-primary-strong);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-control);
  letter-spacing: 0.04em;
}

.empty-card strong {
  margin-top: var(--space-1);
  color: var(--color-text);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-emphasis);
}

/* 四宫格，与 Prototype 的快速体验区一致；窄屏退回单列。 */
.quick-questions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
}

@media (max-width: 520px) {
  .quick-questions {
    grid-template-columns: minmax(0, 1fr);
  }
}

.quick-questions button {
  width: 100%;
  height: 100%;
  display: grid;
  gap: var(--space-0-5);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text);
  background: var(--color-surface);
  font-size: var(--font-size-body);
  text-align: left;
  transition: var(--transition-interactive);
}

.quick-questions__category {
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-control);
}

.quick-questions button:hover {
  border-color: #cdd7fd;
  background: var(--color-primary-soft);
}

.quick-questions button:hover .quick-questions__category {
  color: var(--color-primary-strong);
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
