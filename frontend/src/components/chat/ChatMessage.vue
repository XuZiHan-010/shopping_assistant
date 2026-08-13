<script setup lang="ts">
import {
  AlertTriangle,
  Check,
  Loader,
  RotateCcw,
  ShieldCheck,
  Square,
  ThumbsDown,
  ThumbsUp,
} from '@lucide/vue'
import { computed } from 'vue'

import DetailTable from '@/components/insights/DetailTable.vue'
import type {
  AnalysisSource,
  ChatMessage as ChatMessageModel,
  FeedbackIntent,
  QualityStatus,
} from '@/types/chat'
import { describeError } from '@/utils/errorCopy'

const props = defineProps<{
  message: ChatMessageModel
  selected?: boolean
}>()

const emit = defineEmits<{
  retry: [localId: string]
  cancel: [localId: string]
  select: [localId: string]
  feedback: [localId: string, intent: FeedbackIntent]
}>()

const latestStage = computed(() => props.message.steps.at(-1)?.label ?? '正在准备')
const completedSteps = computed(() =>
  props.message.answer?.thinkingSteps?.length
    ? props.message.answer.thinkingSteps
    : props.message.steps,
)
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
const feedbackErrorCopy = computed(() =>
  props.message.feedbackError ? describeError(props.message.feedbackError) : undefined,
)

/**
 * 是否展示重试按钮，直接看后端/`toAppError` 给的 `retryable`，不是看
 * `status`。`REQUEST_IN_PROGRESS`、`IDEMPOTENCY_KEY_REUSED` 这类错误
 * `retryable` 恒为 false——后端说这条请求正在处理或已被判定为重复提交，
 * 再点重试只会打成循环或制造第二条重复请求，UI 只展示提示文案、等待，
 * 不给出会诱导重复点击的按钮。
 */
const canRetryError = computed(() => props.message.error?.retryable ?? false)

const QUALITY_LABELS: Record<QualityStatus, string> = {
  PASSED: '前后比对通过',
  DEGRADED: '校验未通过，已使用稳定兜底',
  FAILED: '前后比对未通过',
  NOT_RUN: '未执行校验',
}

const SOURCE_LABELS: Record<AnalysisSource, string> = {
  DATABASE: '经营数据',
  KNOWLEDGE: '知识库',
  ATTACHMENT: '附件',
  MEMORY: '商家记忆',
  FALLBACK: '兜底回答',
  NONE: '无外部来源',
}

const qualityTrace = computed(() => {
  const quality = props.message.answer?.quality
  if (!quality) return undefined
  return {
    ...quality,
    label: QUALITY_LABELS[quality.status],
    sourceLabels: quality.sources.map((source) => SOURCE_LABELS[source]),
  }
})

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
    sources:
      quality.sources.length > 0
        ? quality.sources.map((source) => SOURCE_LABELS[source]).join('、')
        : undefined,
  }
})

// 历史回答的反馈状态必须由详情接口同时返回；只有回答 ID 与该状态都可信时才
// 开放修改，避免用本地默认值覆盖服务端的真实反馈。
const canSendFeedback = computed(
  () =>
    Boolean(props.message.answer?.id) &&
    (props.message.origin !== 'history' || props.message.feedback !== undefined),
)

// 只有「已完成且带回答载荷」的助手消息才是可选中的轮次。用户消息没有回答，
// 选中它只会让 currentAnswer 找不到目标而回落到最后一轮——看起来像点错了。
const isSelectableRound = computed(
  () => props.message.role === 'assistant' && props.message.status === 'complete',
)
// 纯明细的 answer 按后端契约是精确空串；表格仍独立渲染，但不能留下一个可聚焦的
// 空按钮或空文本段落。用户消息与分析型回答则继续按原样展示正文。
const hasAnswerText = computed(() => props.message.text.trim().length > 0)
// 常规 METRIC 的 `data` 只是趋势行的附带数据来源（图表面板自己的 <details> 已经
// 用它渲染过一份可访问数据表），不按 answer_mode 过滤会产生重复表格。受控生成
// 指标例外：它可能被截断并带签名 CSV，必须在消息中复用 DetailTable 露出完整下载入口。
const showDetailTable = computed(
  () =>
    props.message.origin === 'live' &&
    props.message.status === 'complete' &&
    (props.message.answer?.mode === 'DETAIL' || props.message.answer?.metric?.generated === true) &&
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
      <section
        v-if="qualityTrace"
        class="chat-message__quality"
        :class="`chat-message__quality--${qualityTrace.status.toLowerCase()}`"
        role="group"
        aria-label="质量校验轨迹"
      >
        <div class="chat-message__quality-heading">
          <ShieldCheck :size="15" aria-hidden="true" />
          <strong>{{ qualityTrace.label }}</strong>
          <span
            v-if="qualityTrace.attempts > 0"
            class="chat-message__quality-attempts"
            data-testid="quality-attempts"
          >
            经过 {{ qualityTrace.attempts }} 次校验
          </span>
        </div>
        <details
          v-if="qualityTrace.notes.length > 0"
          class="chat-message__quality-notes"
          data-testid="quality-notes"
        >
          <summary>查看校验记录</summary>
          <ul>
            <li v-for="note in qualityTrace.notes" :key="note">{{ note }}</li>
          </ul>
        </details>
        <div class="chat-message__quality-sources" aria-label="分析来源">
          <span
            v-for="(source, index) in qualityTrace.sourceLabels"
            :key="`${source}-${index}`"
            data-testid="quality-source"
          >
            {{ source }}
          </span>
        </div>
      </section>

      <p v-if="degradeNotice" class="chat-message__degraded" data-testid="degraded-notice">
        <AlertTriangle :size="13" aria-hidden="true" />
        <span>
          <strong>演示数据</strong>
          {{ degradeNotice.reason }}
          <span v-if="degradeNotice.sources" class="chat-message__degraded-sources">
            分析来源：{{ degradeNotice.sources }}
          </span>
        </span>
      </p>

      <template v-if="isSelectableRound">
        <section v-if="completedSteps.length" class="chat-message__thinking" aria-label="执行步骤">
          <strong>执行完成</strong>
          <div
            v-for="(step, index) in completedSteps"
            :key="`${step.node}-${index}`"
            data-testid="thinking-step"
          >
            {{ step.label }}
          </div>
        </section>
        <button
          v-if="hasAnswerText"
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
          历史明细仅保留{{ message.answer?.data?.columns?.length ?? 0 }}列、
          {{
            message.answer?.data?.totalRows ?? 0
          }}行的元数据；重新提问可查看最新的数据表格与下载链接。
        </p>
      </template>
      <p v-else-if="hasAnswerText" class="chat-message__text">{{ message.text }}</p>

      <section
        v-if="canSendFeedback"
        class="chat-message__feedback"
        role="group"
        aria-label="回答反馈"
      >
        <div class="chat-message__feedback-row">
          <span
            v-if="message.feedbackPending || message.feedbackPersisted"
            class="chat-message__feedback-status"
            data-testid="feedback-status"
            aria-live="polite"
          >
            {{ message.feedbackPending ? '保存中' : '已记录' }}
          </span>
          <button
            type="button"
            aria-label="采纳本轮回答"
            :aria-pressed="message.feedback?.isAdopted === true"
            :disabled="message.feedbackPending"
            @click="emit('feedback', message.localId, { type: 'ADOPT' })"
          >
            <Check :size="14" aria-hidden="true" />
            <span>{{ message.feedback?.isAdopted ? '已采纳' : '采纳' }}</span>
          </button>
          <button
            type="button"
            aria-label="给本轮回答点赞"
            :aria-pressed="message.feedback?.reaction === 'LIKE'"
            :disabled="message.feedbackPending"
            @click="emit('feedback', message.localId, { type: 'REACT', reaction: 'LIKE' })"
          >
            <ThumbsUp :size="14" aria-hidden="true" />
            <span>点赞</span>
          </button>
          <button
            type="button"
            aria-label="给本轮回答点踩"
            :aria-pressed="message.feedback?.reaction === 'DISLIKE'"
            :disabled="message.feedbackPending"
            @click="emit('feedback', message.localId, { type: 'REACT', reaction: 'DISLIKE' })"
          >
            <ThumbsDown :size="14" aria-hidden="true" />
            <span>点踩</span>
          </button>
        </div>
        <p
          v-if="feedbackErrorCopy"
          class="chat-message__feedback-error"
          data-testid="feedback-error"
          aria-live="polite"
        >
          {{ feedbackErrorCopy.title }}
        </p>
      </section>
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

.chat-message__quality {
  margin: 0 0 var(--space-2);
  padding: var(--space-2) var(--space-2-5);
  border: 1px solid #d9e3ef;
  border-left-width: 3px;
  border-radius: var(--radius-small);
  background: #f8fafc;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}

.chat-message__quality--passed {
  border-left-color: #2f7d5b;
}

.chat-message__quality--degraded,
.chat-message__quality--not_run {
  border-left-color: #b47b18;
}

.chat-message__quality--failed {
  border-left-color: #b44b4b;
}

.chat-message__quality-heading {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-1-5);
}

.chat-message__quality-heading strong {
  color: var(--color-text);
}

.chat-message__quality-attempts {
  color: var(--color-text-secondary);
}

.chat-message__quality-notes {
  margin-top: var(--space-1-5);
}

.chat-message__quality-notes summary {
  width: fit-content;
  cursor: pointer;
  color: var(--color-primary-strong);
}

.chat-message__quality-notes ul {
  margin: var(--space-1) 0 0;
  padding-left: var(--space-4);
}

.chat-message__quality-sources {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-top: var(--space-1-5);
}

.chat-message__quality-sources span {
  padding: 1px var(--space-1-5);
  border: 1px solid #d4deea;
  border-radius: 999px;
  background: #fff;
}

.chat-message__history-notice {
  margin: var(--space-2) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}

.chat-message__thinking {
  display: grid;
  gap: var(--space-1);
  margin: 0 0 var(--space-2);
  padding: var(--space-2) var(--space-2-5);
  border-left: 3px solid #8ba9cb;
  color: var(--color-text-secondary);
  background: #f8fafc;
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}

.chat-message__thinking strong {
  color: var(--color-text);
}

.chat-message__feedback {
  margin-top: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border);
}

.chat-message__feedback-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-1-5);
}

.chat-message__feedback-row button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  background: #fff;
  font: inherit;
  font-size: var(--font-size-caption);
  transition: var(--transition-colors);
}

.chat-message__feedback-row button:hover:not(:disabled) {
  border-color: #9cb2ce;
  color: var(--color-primary-strong);
  background: #f4f8fd;
}

.chat-message__feedback-row button[aria-pressed='true'] {
  border-color: #8ba9cb;
  color: #164e75;
  background: #e7f1fb;
}

.chat-message__feedback-row button:disabled {
  cursor: wait;
  opacity: 0.58;
}

.chat-message__feedback-status {
  padding: 2px var(--space-2);
  border-radius: 999px;
  color: #2f654d;
  background: #e9f4ee;
  font-size: var(--font-size-caption);
}

.chat-message__feedback-error {
  margin: var(--space-1-5) 0 0;
  color: var(--color-danger-text);
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
