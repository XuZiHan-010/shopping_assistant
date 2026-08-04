<script setup lang="ts">
import { ArrowUp, Paperclip } from '@lucide/vue'
import { nextTick, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ busy?: boolean }>(), { busy: false })

const emit = defineEmits<{
  submit: [message: string]
}>()

const message = ref('')
const textareaElement = ref<HTMLTextAreaElement | null>(null)

/**
 * 输入框随内容长高。没有用 CSS 的 field-sizing: content——它目前只有 Chromium
 * 支持，Firefox 与 Safari 会直接退回固定单行。
 */
function resizeTextarea(): void {
  const element = textareaElement.value
  if (!element) return

  // 先归零再读 scrollHeight：不归零的话，内容变短时 scrollHeight 仍是上一次被
  // 撑开的高度，输入框就只会长、不会缩。max-height 交给 CSS 封顶。
  element.style.height = 'auto'
  element.style.height = `${element.scrollHeight}px`
}

// 覆盖输入、粘贴、发送后清空——都是 message 变化，一处接住就够。
watch(message, () => void nextTick(resizeTextarea))

function submitMessage(): void {
  const content = message.value.trim()
  // 上一轮在途时不发。Store 那层也有同样的守卫（那才是权威），这里只是不让用户
  // 白敲一次回车——两层都要有：输入区可能被别的入口复用。
  if (!content || props.busy) return

  emit('submit', content)
  message.value = ''
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return

  event.preventDefault()
  submitMessage()
}
</script>

<template>
  <form class="chat-composer" @submit.prevent="submitMessage">
    <div class="chat-composer__main">
      <button
        class="chat-composer__attachment"
        type="button"
        aria-label="附件功能将在后续版本提供"
        title="附件功能将在后续版本提供"
        disabled
      >
        <Paperclip :size="18" aria-hidden="true" />
      </button>
      <textarea
        ref="textareaElement"
        v-model="message"
        name="merchant-question"
        rows="1"
        autocomplete="off"
        aria-label="输入问题"
        placeholder="输入经营问题…"
        @keydown="handleKeydown"
      ></textarea>
      <button
        class="chat-composer__send"
        type="submit"
        :aria-label="busy ? '上一轮回答仍在进行中' : '发送问题'"
        :disabled="!message.trim() || busy"
      >
        <ArrowUp :size="18" aria-hidden="true" />
      </button>
    </div>
    <div class="chat-composer__footnote">
      <span>Enter 发送 · Shift + Enter 换行</span>
      <span>附件分析将在后续版本提供</span>
    </div>
  </form>
</template>

<style scoped>
.chat-composer {
  flex: none;
  padding: var(--space-2-5) var(--space-3) var(--space-2);
  border-top: 1px solid var(--color-border);
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(16px);
}

.chat-composer__main {
  min-height: 44px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 36px;
  gap: var(--space-2);
  align-items: end;
  padding: var(--space-1);
  border: 1px solid var(--color-border-strong);
  border-radius: 15px;
  background: #f8f9fc;
  transition: var(--transition-interactive);
}

.chat-composer__main:focus-within {
  border-color: #aabafb;
  box-shadow: 0 0 0 3px rgba(79, 110, 247, 0.09);
}

.chat-composer__attachment,
.chat-composer__send {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-control);
  transition: var(--transition-interactive);
}

.chat-composer__attachment {
  color: var(--color-text-secondary);
  background: transparent;
}

.chat-composer__attachment:hover:not(:disabled) {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.chat-composer__attachment:disabled {
  color: var(--color-text-muted);
  cursor: default;
}

textarea {
  width: 100%;
  min-height: 24px;
  max-height: 120px;
  align-self: center;
  resize: none;
  overflow: auto;
  border: 0;
  outline: 0;
  padding: var(--space-1) var(--space-0-5);
  color: var(--color-text);
  background: transparent;
  font-size: var(--font-size-control);
  line-height: var(--line-height-body);
}

textarea::placeholder {
  color: #99a3b3;
}

.chat-composer__send {
  color: #fff;
  background: var(--color-primary);
}

.chat-composer__send:hover:not(:disabled) {
  background: var(--color-primary-strong);
  transform: translateY(-1px);
}

.chat-composer__send:disabled {
  color: #9ea8b8;
  background: #e5e9ef;
  cursor: default;
}

.chat-composer__footnote {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2-5);
  padding: var(--space-1) var(--space-1) 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}

@media (max-width: 560px) {
  .chat-composer__footnote span:last-child {
    display: none;
  }
}
</style>
