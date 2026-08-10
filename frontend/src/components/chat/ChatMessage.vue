<script setup lang="ts">
import { AlertTriangle, Loader, RotateCcw, Square } from '@lucide/vue'
import { computed } from 'vue'

import DetailTable from '@/components/insights/DetailTable.vue'
import type { ChatMessage as ChatMessageModel } from '@/types/chat'
import { describeError } from '@/utils/errorCopy'

const props = defineProps<{
  message: ChatMessageModel
  selected?: boolean
}>()

const emit = defineEmits<{
  retry: [localId: string]
  cancel: [localId: string]
  select: [localId: string]
}>()

const latestStage = computed(() => props.message.steps.at(-1)?.label ?? '正在准备')
const isRunning = computed(
  () => props.message.status === 'pending' || props.message.status === 'streaming',
)

/**
 * Store 只存 `AppError`，不存文案——同一个错误在消息卡片与全局提示条里的
 * 措辞并不相同，文案统一在展示处按需生成（`describeError`，
 * `src/utils/errorCopy.ts`）。
 */
const errorCopy = computed(() =>
  props.message.error ? describeError(props.message.error) : undefined,
)

/**
 * 是否展示重试按钮，直接看后端/`toAppError` 给的 `retryable`，不是看
 * `status`。`REQUEST_IN_PROGRESS`、`IDEMPOTENCY_KEY_REUSED` 这类错误
 * `retryable` 恒为 false——后端说这条请求正在处理或已被判定为重复提交，
 * 再点重试只会打成循环或制造第二条重复请求，UI 只展示提示文案、等待，
 * 不给出会诱导重复点击的按钮。
 */
const canRetryError = computed(() => props.message.error?.retryable ?? false)

/**
 * 降级必须对用户可见（AGENTS.md R7、前端方案 §10）。
 *
 * 当前演示走的是后端 FakeAgent 的输出，`analysis_sources` 是 `['FALLBACK']`、
 * `degraded` 为 true。不显示的话，页面上的 ¥256,920 看起来就和真实经营数据
 * 一模一样——这正是 R7 要禁止的。
 */
const degradeNotice = computed(() => {
  const quality = props.message.answer?.quality
  if (!quality?.degraded) return undefined

  return {
    reason: quality.degradedReason ?? '本次回答未接入真实数据源，仅供演示参考。',
    sources: quality.sources.join('、'),
  }
})

// 只有「已完成且带回答载荷」的助手消息才是可选中的轮次。用户消息没有回答，
// 选中它只会让 currentAnswer 找不到目标而回落到最后一轮——看起来像点错了。
const isSelectableRound = computed(
  () => props.message.role === 'assistant' && props.message.status === 'complete',
)
// METRIC 回答的 `data` 只是趋势行的附带数据来源（图表面板自己的 <details> 已经
// 用它渲染过一份可访问数据表），不按 answer_mode 过滤的话，同一批行会在聊天
// 消息里又完整渲染一次「经营明细」表格——两张表、没有下载入口，纯粹是重复。
const showDetailTable = computed(
  () =>
    props.message.origin === 'live' &&
    props.message.status === 'complete' &&
    props.message.answer?.mode === 'DETAIL' &&
    props.message.answer?.data,
)
// 历史会话不重放明细数据（后端不落库整张明细表），但仍应说明「为什么这轮
// 没有表格」，而不是让用户以为这轮回答本来就没有数据。
const showHistoricalDataNotice = computed(
  () =>
    props.message.origin === 'history' &&
    props.message.status === 'complete' &&
    props.message.answer?.mode === 'DETAIL' &&
    Boolean(props.message.answer?.data),
)
</script>

<template>
  <!-- 卡片本身不再承担点击选中：<article> 不可聚焦，鼠标能做的键盘做不到。
       选中改由下面那个真正的 <button> 承担（以及 ConversationNav 的目录条目）。 -->
  <article class="chat-message" :class="`chat-message--${message.role}`" data-testid="chat-message">
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
      <span data-testid="notice-text">{{ errorCopy?.title }}{{ errorCopy?.detail }}</span>
      <!-- 取消是用户主动发起的操作，不是「值不值得重试」的错误，重新回答的
           入口始终展示，不看 error.retryable。 -->
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
      <span data-testid="notice-text">{{ errorCopy?.title }}{{ errorCopy?.detail }}</span>
      <button
        v-if="canRetryError"
        type="button"
        data-testid="retry-button"
        aria-label="重试本轮问题"
        @click.stop="emit('retry', message.localId)"
      >
        <RotateCcw :size="12" aria-hidden="true" />
        <span>重试</span>
      </button>
    </p>

    <template v-else>
      <p v-if="degradeNotice" class="chat-message__degraded" data-testid="degraded-notice">
        <AlertTriangle :size="13" aria-hidden="true" />
        <span>
          <strong>演示数据</strong>
          {{ degradeNotice.reason }}
          <span class="chat-message__degraded-sources">分析来源：{{ degradeNotice.sources }}</span>
        </span>
      </p>

      <template v-if="isSelectableRound">
        <button
          class="chat-message__select"
          type="button"
          data-testid="select-round"
          :aria-current="selected ? 'true' : undefined"
          :aria-label="`查看本轮分析：${message.text.slice(0, 30)}`"
          @click="emit('select', message.localId)"
        >
          {{ message.text }}
        </button>
        <DetailTable
          v-if="showDetailTable"
          :data="message.answer!.data!"
          :export-info="message.answer!.export"
        />
        <p
          v-else-if="showHistoricalDataNotice"
          class="chat-message__history-notice"
          data-testid="history-detail-notice"
        >
          历史明细数据未保留完整表格，重新提问可查看最新的数据表格与下载链接。
        </p>
      </template>
      <p v-else class="chat-message__text">{{ message.text }}</p>
    </template>
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

/* 选中态的轮次是一个真正的按钮：可 Tab 到、可 Enter/Space 触发、有 aria-current。
   外观刻意保持成正文，不做成按钮样子——它承载的就是回答文本本身。 */
.chat-message__select {
  width: 100%;
  display: block;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: var(--radius-small);
  color: var(--color-text);
  background: transparent;
  font: inherit;
  font-size: var(--font-size-body);
  line-height: 1.6;
  text-align: left;
  white-space: pre-wrap;
  transition: var(--transition-colors);
}

.chat-message__select:hover {
  color: var(--color-primary-strong);
}

.chat-message__select[aria-current='true'] {
  box-shadow: -3px 0 0 0 var(--color-primary);
  padding-left: var(--space-2);
}

.chat-message__degraded {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: 0 0 var(--space-2);
  padding: var(--space-2) var(--space-2-5);
  border: 1px solid #f2d69b;
  border-radius: var(--radius-small);
  color: #6b4a05;
  background: #fdf6e3;
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}

.chat-message__degraded strong {
  margin-right: var(--space-1);
}

.chat-message__degraded-sources {
  display: block;
  opacity: 0.85;
}

.chat-message__history-notice {
  margin: var(--space-2) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
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
