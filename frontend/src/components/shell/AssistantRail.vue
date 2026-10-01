<script setup lang="ts">
/**
 * 运营助手栏（W Task 6，设计说明 §2.1、§3.2）：从原整页 `OpsAssistantView` 抽出，
 * 常驻商家工作台外壳的 `#assistant-rail`，默认收起。开合、快捷键与 Esc 由外壳和
 * `stores/rail.ts` 负责；对话、目录、反馈的逻辑全部仍在 `stores/opsChat.ts`。
 *
 * - 工具行只显示工具名与状态摘要；参数与结果不会出现在事件里，也不会渲染；
 * - 降级原因随回答展示，来源级降级逐条列出（R7）；
 * - 页面上的「问助手」、简报预填与「猜你想问」都只填入输入框，不代为发送（D18④）；
 * - 对话历史在头部「历史」面板里（新建、浏览、打开、删除），侧栏不放对话记录；
 * - 会话目录在第一次打开助手栏、且外壳已恢复出当前商家后才拉取——收起时不发请求，
 *   也不会在商家恢复之前抢着建会话；换商家后目录被会话态重置清空，打开着就重新拉。
 *
 * 聊天区沿用 `ops-view__*` 类名：Mock / 真实后端 E2E 以 `.ops-view__bubble`、
 * `.ops-view__log` 等定位回答，改名会让这些断言失去目标。
 */
import { Plus, Sparkles, X } from '@lucide/vue'
import { computed, defineAsyncComponent, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { MAX_HISTORY_MESSAGES } from '@/api/adapters/merchantConversations'
import OpsConversationList from '@/components/opsChat/OpsConversationList.vue'
import { useAuthStore } from '@/stores/auth'
import { useOpsChatStore } from '@/stores/opsChat'
import type { OpsMessage } from '@/stores/opsChat'
import { useRailStore } from '@/stores/rail'

// 图表只在回合带可视化时挂载（`v-if`），ECharts 不进首屏（`check-first-paint.mjs`）。
const MetricChartPanel = defineAsyncComponent(
  () => import('@/components/insights/MetricChartPanel.vue'),
)

const store = useOpsChatStore()
const rail = useRailStore()
const auth = useAuthStore()
const { t } = useI18n()

const input = ref('')
const inputElement = ref<HTMLTextAreaElement | null>(null)
const bodyElement = ref<HTMLDivElement | null>(null)

// 助手栏常驻，不能依赖子页面重建来清理输入；同一商家改显示语言不清空。
watch(
  () => auth.selected?.merchantId,
  () => {
    input.value = ''
  },
  { flush: 'sync' },
)

const errorText = computed(() => (store.errorKey ? t(store.errorKey) : store.errorMessage))
const lastTurn = computed(() => [...store.messages].reverse().find((message) => message.turn)?.turn)
const lastSuggestions = computed(() => lastTurn.value?.suggestions ?? [])
// 只有 `query_metrics`/`attribute_change` 调用过的回合才会 `enabled=true`
// （契约 §8.7.11）；其余回合面板不挂载，不展示一个空图表占位。
const lastChart = computed(() => lastTurn.value?.chart)

function focusInput(): void {
  inputElement.value?.focus({ preventScroll: true })
}

function takePrefill(): void {
  const text = store.consumePrefill()
  if (text) input.value = text
}

async function fillInput(text: string): Promise<void> {
  input.value = text
  await nextTick()
  focusInput()
}

async function submit(): Promise<void> {
  const text = input.value.trim()
  if (!text || store.busy) return
  input.value = ''
  // 在「历史」面板里直接发送时切回对话面板，回答才看得见。
  rail.showChat()
  await store.send(text)
}

/** 中文输入法选词时的回车只是确认候选词，不能当成发送。 */
function onEnter(event: KeyboardEvent): void {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  void submit()
}

function feedbackReasonInput(messageId: string, event: Event): void {
  store.setFeedbackReason(messageId, (event.target as HTMLInputElement).value)
}

function react(message: OpsMessage, reaction: 'LIKE' | 'DISLIKE'): void {
  const next = message.feedback?.reaction === reaction ? null : reaction
  const reason = message.feedbackReasonDraft?.trim()
  void store.sendFeedback(message.id, {
    kind: 'REACTION',
    reaction: next,
    ...(next && reason ? { reason } : {}),
  })
}

function startNew(): void {
  store.startNew()
  rail.showChat()
  void nextTick(focusInput)
}

function openFromHistory(id: string): void {
  rail.showChat()
  void store.openConversation(id)
}

onMounted(takePrefill)
// 助手栏常驻外壳：任何页面的「问助手」都经 `opsChat.prefill()` 到这里，只填不发。
watch(() => store.pendingInput, takePrefill)

// 打开时把焦点交给输入框（`post`：等外壳去掉 `hidden` 之后再聚焦）。
watch(
  () => rail.open,
  (open) => {
    if (open) focusInput()
  },
  { flush: 'post' },
)

watch(
  () => [rail.open, auth.selected?.merchantId, rail.pendingConversationId] as const,
  ([open, merchantId]) => {
    if (!open || !merchantId) return
    if (store.directoryStatus === 'idle') void store.loadConversations()
    const pending = rail.takePendingConversation()
    if (pending) void store.openConversation(pending)
  },
  { immediate: true },
)

// 新消息与流式片段到达时滚到底部。
watch(
  () => store.messages,
  () => {
    const body = bodyElement.value
    if (body) body.scrollTop = body.scrollHeight
  },
  { flush: 'post' },
)
</script>

<template>
  <div class="rail">
    <header class="rail__head" data-testid="ops-header">
      <span class="rail__mark" aria-hidden="true"><Sparkles :size="16" /></span>
      <div class="rail__heading">
        <h2 class="rail__title">{{ t('opsAssistant.title') }}</h2>
        <span class="rail__sub">{{ t('shell.railSub') }}</span>
      </div>
      <button
        type="button"
        class="rail__pill"
        data-test="rail-history-toggle"
        aria-controls="assistant-rail-history"
        :aria-pressed="rail.historyOpen ? 'true' : 'false'"
        @click="rail.toggleHistory()"
      >
        {{ t('shell.railHistory') }}
      </button>
      <button
        type="button"
        class="rail__icon"
        data-test="rail-new"
        :aria-label="t('opsAssistant.newConversation')"
        :title="t('opsAssistant.newConversation')"
        :disabled="store.busy"
        @click="startNew"
      >
        <Plus :size="18" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="rail__icon"
        data-test="rail-close"
        :aria-label="t('shell.railClose')"
        :title="t('shell.railClose')"
        @click="rail.hide()"
      >
        <X :size="18" aria-hidden="true" />
      </button>
    </header>

    <div ref="bodyElement" class="rail__body">
      <div v-show="rail.historyOpen" id="assistant-rail-history" class="rail__history">
        <OpsConversationList
          :items="store.conversations"
          :current-id="store.conversationId"
          :status="store.directoryStatus"
          :has-more="store.conversationsNextCursor !== null"
          :disabled="store.busy"
          @open="openFromHistory"
          @remove="(id) => void store.removeConversation(id)"
          @create="startNew"
          @load-more="() => void store.loadMoreConversations()"
          @retry="() => void store.loadConversations()"
        />
      </div>

      <section
        v-show="!rail.historyOpen"
        class="ops-view__chat"
        :aria-label="t('opsAssistant.title')"
      >
        <p class="ops-view__scope" role="note">{{ t('opsAssistant.scopeNotice') }}</p>

        <p v-if="store.historyTruncated" class="ops-view__muted" role="note">
          {{ t('opsAssistant.historyTruncated', { count: MAX_HISTORY_MESSAGES }) }}
        </p>

        <div class="ops-view__log" aria-live="polite">
          <div
            v-for="message in store.messages"
            :key="message.id"
            class="ops-view__bubble"
            :class="{ 'ops-view__bubble--user': message.role === 'user' }"
          >
            <div
              v-for="call in message.toolCalls"
              :key="call.callId"
              class="ops-view__tool"
              data-test="ops-tool-row"
            >
              {{ call.toolName }} · {{ call.summary }}
            </div>
            <div v-if="message.text">{{ message.text }}</div>
            <p v-if="message.turn?.envelope.degraded" class="ops-view__degraded" role="note">
              {{
                t('opsAssistant.degraded', {
                  reason: message.turn.envelope.degradedReason ?? t('opsAssistant.degradedUnknown'),
                })
              }}
            </p>
            <template v-if="message.turn">
              <p
                v-for="source in message.turn.envelope.analysisSources.filter(
                  (s) => s.degraded && s.degradedReason,
                )"
                :key="source.source"
                class="ops-view__muted"
              >
                {{
                  t('opsAssistant.sourceDegraded', {
                    source: source.source,
                    reason: source.degradedReason,
                  })
                }}
              </p>
            </template>
            <div
              v-if="message.role === 'assistant' && message.turn"
              class="ops-view__feedback"
              data-test="ops-feedback"
              role="group"
              :aria-label="t('opsAssistant.feedbackGroup')"
            >
              <div class="ops-view__feedback-actions">
                <button
                  type="button"
                  class="ops-view__button"
                  data-test="ops-adopt"
                  :disabled="message.feedbackPending"
                  :aria-pressed="message.feedback?.adopted === true"
                  @click="
                    void store.sendFeedback(message.id, {
                      kind: 'ADOPTION',
                      adopted: !message.feedback?.adopted,
                    })
                  "
                >
                  {{
                    message.feedback?.adopted ? t('opsAssistant.adopted') : t('opsAssistant.adopt')
                  }}
                </button>
                <button
                  type="button"
                  class="ops-view__button"
                  data-test="ops-like"
                  :disabled="message.feedbackPending"
                  :aria-pressed="message.feedback?.reaction === 'LIKE'"
                  @click="react(message, 'LIKE')"
                >
                  {{ t('opsAssistant.like') }}
                </button>
                <button
                  type="button"
                  class="ops-view__button"
                  data-test="ops-dislike"
                  :disabled="message.feedbackPending"
                  :aria-pressed="message.feedback?.reaction === 'DISLIKE'"
                  @click="react(message, 'DISLIKE')"
                >
                  {{ t('opsAssistant.dislike') }}
                </button>
                <span
                  v-if="message.feedbackPending || message.feedbackPersisted"
                  data-test="ops-feedback-status"
                  class="ops-view__muted"
                  aria-live="polite"
                >
                  {{
                    message.feedbackPending
                      ? t('opsAssistant.feedbackPending')
                      : t('opsAssistant.feedbackSaved')
                  }}
                </span>
              </div>
              <input
                type="text"
                data-test="ops-reason"
                class="ops-view__reason"
                :value="message.feedbackReasonDraft ?? ''"
                :disabled="message.feedbackPending"
                :aria-label="t('opsAssistant.reasonLabel')"
                :placeholder="t('opsAssistant.reasonPlaceholder')"
                maxlength="500"
                @input="feedbackReasonInput(message.id, $event)"
              />
              <p
                v-if="message.feedbackError"
                data-test="ops-feedback-error"
                class="ops-view__error"
                role="alert"
              >
                {{
                  message.feedbackError === 'feedbackFailed'
                    ? t('opsAssistant.feedbackFailed')
                    : message.feedbackError
                }}
              </p>
            </div>
          </div>
        </div>

        <MetricChartPanel v-if="lastChart?.enabled" :chart="lastChart" />

        <div v-if="lastSuggestions.length > 0" class="ops-view__suggestions">
          <span class="ops-view__muted">{{ t('opsAssistant.suggestionsLabel') }}</span>
          <button
            v-for="suggestion in lastSuggestions"
            :key="suggestion"
            type="button"
            class="ops-view__button ops-view__suggestion"
            data-test="ops-suggestion"
            :disabled="store.busy"
            @click="fillInput(suggestion)"
          >
            <Sparkles :size="14" aria-hidden="true" />
            <span>{{ suggestion }}</span>
          </button>
        </div>
      </section>
    </div>

    <p v-if="errorText" class="ops-view__error rail__error" role="alert">{{ errorText }}</p>

    <form class="ops-view__composer" data-test="ops-form" @submit.prevent="submit">
      <textarea
        ref="inputElement"
        v-model="input"
        data-test="ops-input"
        rows="2"
        :aria-label="t('opsAssistant.inputLabel')"
        :placeholder="t('opsAssistant.inputPlaceholder')"
        @keydown.enter.exact="onEnter"
      />
      <button
        type="submit"
        class="ops-view__button ops-view__button--primary"
        :disabled="store.busy || !input.trim()"
      >
        {{ store.busy ? t('opsAssistant.sending') : t('opsAssistant.send') }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.rail {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  color: var(--ink);
}

/* ---------- 头部：标题、历史、新建、收起 ---------- */
.rail__head {
  display: flex;
  flex: none;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 12px 10px 12px 16px;
  border-bottom: 1px solid var(--line);
}

.rail__mark {
  width: 30px;
  height: 30px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: var(--on-accent);
  background: var(--accent);
}

.rail__heading {
  flex: 1;
  min-width: 0;
}

.rail__title {
  margin: 0;
  overflow: hidden;
  font-family: inherit;
  font-size: 14px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rail__sub {
  display: block;
  overflow: hidden;
  font-size: 12px;
  color: var(--ink-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rail__pill {
  flex: none;
  height: 30px;
  padding: 0 11px;
  border: 1px solid var(--line-strong);
  border-radius: 99px;
  color: var(--ink);
  background: var(--card);
  font-size: 12.5px;
  font-weight: 600;
  transition: background-color 150ms;
}

.rail__pill:hover,
.rail__pill[aria-pressed='true'] {
  background: var(--well);
}

.rail__icon {
  width: 32px;
  height: 32px;
  flex: none;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 8px;
  color: var(--ink-soft);
  background: none;
  transition:
    background-color 150ms,
    color 150ms;
}

.rail__icon:hover {
  color: var(--ink);
  background: var(--hover);
}

.rail__icon:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ---------- 正文：历史面板 / 对话 ---------- */
.rail__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.rail__history {
  padding: 12px;
}

.ops-view__chat {
  display: grid;
  gap: var(--space-3);
  min-width: 0;
  padding: 16px 14px 8px;
}

.ops-view__scope {
  margin: 0;
  padding: var(--space-3);
  border-radius: 10px;
  color: var(--ink-2);
  background: var(--well);
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.ops-view__muted {
  margin: 0;
  color: var(--ink-2);
  font-size: var(--font-size-caption);
}

.ops-view__log {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.ops-view__bubble {
  max-width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--card);
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  /* 单号、链接这类无空格长串也要在气泡内折行，否则窄屏会被撑出横向滚动。 */
  overflow-wrap: anywhere;
}

.ops-view__bubble--user {
  align-self: flex-end;
  max-width: 86%;
  border-color: transparent;
  border-radius: 14px 14px 4px 14px;
  color: var(--ground);
  background: var(--ink);
}

.ops-view__tool {
  color: var(--ink-2);
  font-family: var(--font-mono);
  font-size: 12px;
}

.ops-view__degraded {
  margin: var(--space-2) 0 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-control);
  background: var(--danger-soft);
  color: var(--danger);
}

.ops-view__feedback {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-3);
  white-space: normal;
}

.ops-view__feedback-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}

.ops-view__feedback-actions [aria-pressed='true'] {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.ops-view__reason {
  width: 100%;
  min-width: 0;
  min-height: var(--control-height);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  color: var(--ink);
  background: var(--card);
  font: inherit;
}

.ops-view__suggestions {
  display: grid;
  gap: 8px;
}

.ops-view__suggestion {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 9px 12px;
  border-color: var(--line);
  border-radius: 11px;
  text-align: left;
  font-size: 13.5px;
}

.ops-view__suggestion :deep(svg) {
  flex: none;
  color: var(--accent);
}

.ops-view__suggestion:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.ops-view__error {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-control);
  background: var(--danger-soft);
  color: var(--danger);
  overflow-wrap: anywhere;
}

.rail__error {
  flex: none;
  margin: 0 14px 8px;
}

/* ---------- 输入区 ---------- */
.ops-view__composer {
  display: flex;
  flex: none;
  gap: var(--space-2);
  align-items: flex-end;
  padding: 10px 14px 14px;
  border-top: 1px solid var(--line);
}

.ops-view__composer textarea {
  flex: 1;
  min-width: 0;
  min-height: var(--control-height);
  max-height: 140px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  color: var(--ink);
  background: var(--card);
  font: inherit;
  resize: vertical;
}

.ops-view__button {
  min-height: var(--control-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--card);
  color: var(--ink);
  cursor: pointer;
  overflow-wrap: anywhere;
}

.ops-view__button--primary {
  flex: none;
  border-color: var(--accent);
  background: var(--accent);
  color: var(--on-accent);
}

.ops-view__button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
