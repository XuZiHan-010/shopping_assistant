<script setup lang="ts">
/**
 * 商家运营助手（`n2-conversations-and-feedback` Task 4B 创建；两页合并评审
 * 2026-09-26 评审、2026-09-27 用户裁定「选项 C」后接管 `/`，取代 v1 分析助手
 * `AssistantView`——PRD §15 N2）。
 *
 * 指标查询与归因、商品内容、定价促销、库存、导出、售后、规则口径问答均已
 * 接入，补货、定价、内容与商品变更以草稿形式提交，不代为直接批准（D18④）。
 *
 * - 工具行只显示工具名与状态摘要；参数与结果不会出现在事件里，也不会渲染；
 * - 降级原因随回答展示（R7）；
 * - 简报预填与「猜你想问」都只填入输入框，不代为发送（D18④）。
 */
import { computed, defineAsyncComponent, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { MAX_HISTORY_MESSAGES } from '@/api/adapters/merchantConversations'
import LanguageSwitcher from '@/components/layout/LanguageSwitcher.vue'
import MerchantSwitcher from '@/components/layout/MerchantSwitcher.vue'
import OpsConversationList from '@/components/opsChat/OpsConversationList.vue'
import { useAuthStore } from '@/stores/auth'
import { useOpsChatStore } from '@/stores/opsChat'
import type { OpsMessage } from '@/stores/opsChat'

const MetricChartPanel = defineAsyncComponent(
  () => import('@/components/insights/MetricChartPanel.vue'),
)

const store = useOpsChatStore()
const auth = useAuthStore()
const { t } = useI18n()

const input = ref('')
const inputElement = ref<HTMLTextAreaElement | null>(null)

const errorText = computed(() => (store.errorKey ? t(store.errorKey) : store.errorMessage))
const lastTurn = computed(() => [...store.messages].reverse().find((message) => message.turn)?.turn)
const lastSuggestions = computed(() => lastTurn.value?.suggestions ?? [])
// 只有 `query_metrics`/`attribute_change` 调用过的回合才会 `enabled=true`
// （契约 §8.7.11）；其余回合面板不挂载，不展示一个空图表占位。
const lastChart = computed(() => lastTurn.value?.chart)

function takePrefill(): void {
  const text = store.consumePrefill()
  if (text) input.value = text
}

async function fillInput(text: string): Promise<void> {
  input.value = text
  await nextTick()
  inputElement.value?.focus()
}

async function submit(): Promise<void> {
  const text = input.value.trim()
  if (!text || store.busy) return
  input.value = ''
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

function selectMerchant(displayName: string): void {
  // 只在「合法且确实换了商家」时切换——重复点当前商家不能把用户已有的对话
  // 清掉。`auth.select()`（`selectByDisplayName` 内部调用）已经在换商家时
  // 触发 `dropSession()` → 遍历所有 `registerSessionScopedReset` 注册方，
  // `opsChat` store 已注册（见 `stores/opsChat.ts`），会话与目录会自动清空，
  // 这里不需要再手动调用一次。
  if (displayName === auth.selected?.displayName) return
  if (!auth.displayNames.includes(displayName)) return

  auth.selectByDisplayName(displayName)
  void store.loadConversations()
}

onMounted(async () => {
  takePrefill()
  // 两页合并后 `/` 首次挂载的就是本页（此前只有并存的 v1 `AssistantView`
  // 会在自己的 `onMounted` 里做这一步）。`ensureSession()` 在 `auth.selected`
  // 为空时也会自愈调用 `restore()`，但那里是懒触发、拿到第一个请求才补——
  // 这里显式先做一次，商家切换器能更快出现，且与 v1 原有的初始化顺序一致。
  if (!auth.selected) await auth.restore()
  void store.loadConversations()
})

// 停留在本页时从别处预填（例如另一个标签里的动作）也要接住。
watch(() => store.pendingInput, takePrefill)
</script>

<template>
  <div class="ops-view">
    <header class="ops-view__header" data-testid="ops-header">
      <div class="ops-view__heading">
        <h1 class="ops-view__title">{{ t('opsAssistant.title') }}</h1>
      </div>
      <div class="ops-view__header-actions">
        <LanguageSwitcher />
        <MerchantSwitcher
          v-if="auth.selected"
          :model-value="auth.selected.displayName"
          class="ops-view__merchant-switcher"
          :merchants="auth.displayNames"
          @update:model-value="selectMerchant"
        />
      </div>
      <nav class="ops-view__nav" :aria-label="t('opsAssistant.navLabel')">
        <RouterLink :to="{ name: 'today' }">{{ t('opsAssistant.navToday') }}</RouterLink>
        <RouterLink :to="{ name: 'inventory' }">{{ t('opsAssistant.navInventory') }}</RouterLink>
        <RouterLink :to="{ name: 'approval-list' }">
          {{ t('opsAssistant.navApprovals') }}
        </RouterLink>
        <RouterLink :to="{ name: 'after-sales' }">{{ t('afterSalesView.title') }}</RouterLink>
        <RouterLink :to="{ name: 'customer-signals' }">{{ t('signalsView.title') }}</RouterLink>
        <RouterLink :to="{ name: 'knowledge-base' }">
          {{ t('opsAssistant.navKnowledgeBase') }}
        </RouterLink>
      </nav>
    </header>

    <p class="ops-view__scope" role="note">{{ t('opsAssistant.scopeNotice') }}</p>

    <div class="ops-view__body">
      <OpsConversationList
        :items="store.conversations"
        :current-id="store.conversationId"
        :status="store.directoryStatus"
        :has-more="store.conversationsNextCursor !== null"
        :disabled="store.busy"
        @open="(id) => void store.openConversation(id)"
        @remove="(id) => void store.removeConversation(id)"
        @create="store.startNew"
        @load-more="() => void store.loadMoreConversations()"
        @retry="() => void store.loadConversations()"
      />

      <section class="ops-view__chat" :aria-label="t('opsAssistant.title')">
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
            class="ops-view__button"
            data-test="ops-suggestion"
            :disabled="store.busy"
            @click="fillInput(suggestion)"
          >
            {{ suggestion }}
          </button>
        </div>

        <p v-if="errorText" class="ops-view__error" role="alert">{{ errorText }}</p>

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
      </section>
    </div>
  </div>
</template>

<style scoped>
.ops-view {
  display: grid;
  gap: var(--space-4);
  max-width: 72rem;
  margin: 0 auto;
  padding: var(--space-5) var(--space-4);
  color: var(--color-text);
}
.ops-view__header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
}
.ops-view__heading {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: baseline;
  min-width: 0;
}
.ops-view__title {
  margin: 0;
  font-size: var(--font-size-page-title);
}
.ops-view__header-actions {
  display: flex;
  flex: none;
  gap: var(--space-2);
  align-items: center;
}
.ops-view__merchant-switcher {
  flex: none;
  width: 200px;
}
.ops-view__muted {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}
.ops-view__nav {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
.ops-view__nav a {
  color: var(--color-primary-strong);
}
.ops-view__scope {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-card);
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
  overflow-wrap: anywhere;
}
.ops-view__body {
  display: grid;
  grid-template-columns: minmax(0, 17rem) minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}
.ops-view__chat {
  display: grid;
  gap: var(--space-3);
  min-width: 0;
}
.ops-view__log {
  display: grid;
  gap: var(--space-3);
}
.ops-view__bubble {
  max-width: 42rem;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  white-space: pre-wrap;
  /* 单号、链接这类无空格长串也要在气泡内折行，否则窄屏会被撑出横向滚动。 */
  overflow-wrap: anywhere;
}
.ops-view__bubble--user {
  justify-self: end;
  background: var(--color-primary-soft);
}
.ops-view__tool {
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}
.ops-view__degraded {
  margin: var(--space-2) 0 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-control);
  background: var(--color-danger-surface);
  color: var(--color-danger-text);
}
.ops-view__feedback {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
.ops-view__feedback-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}
.ops-view__feedback-actions [aria-pressed='true'] {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}
.ops-view__reason {
  width: 100%;
  max-width: 28rem;
  min-height: var(--control-height);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  font: inherit;
}
.ops-view__suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}
.ops-view__error {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-control);
  background: var(--color-danger-surface);
  color: var(--color-danger-text);
}
.ops-view__composer {
  display: flex;
  gap: var(--space-2);
  align-items: flex-end;
}
.ops-view__composer textarea {
  flex: 1;
  min-width: 0;
  min-height: var(--control-height);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  font: inherit;
  resize: vertical;
}
.ops-view__button {
  min-height: var(--control-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  color: var(--color-text);
  cursor: pointer;
  overflow-wrap: anywhere;
}
.ops-view__button--primary {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}
.ops-view__button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 40rem) {
  .ops-view {
    padding: var(--space-4) var(--space-3);
  }
  .ops-view__body {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
