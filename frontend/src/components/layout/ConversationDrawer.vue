<script setup lang="ts">
import { Trash2, X } from '@lucide/vue'
import { nextTick, ref, watch } from 'vue'

import { useChatStore } from '@/stores/chat'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const chatStore = useChatStore()
const panelElement = ref<HTMLElement | null>(null)

/**
 * 删除要走两步。会话删掉没有撤销，而删除按钮就贴在标题旁边，误触代价太高。
 * 不用 window.confirm：它阻塞、不可样式化，在测试里也只能靠打桩绕过。
 */
const pendingDeleteId = ref<string | undefined>(undefined)
const deleteError = ref('')

function requestDelete(id: string): void {
  deleteError.value = ''
  pendingDeleteId.value = id
}

function cancelDelete(): void {
  pendingDeleteId.value = undefined
}

async function confirmDelete(id: string): Promise<void> {
  pendingDeleteId.value = undefined
  try {
    await chatStore.removeConversation(id)
  } catch {
    // 之前这里是模板里的游离 Promise：删除失败只在控制台留一条未处理拒绝，
    // 抽屉里那条会话还在，用户会以为自己没点中。
    deleteError.value = '删除失败，请稍后重试。'
  }
}

// 打开时把焦点移进面板，键盘用户才能立刻用 Escape 关闭、用 Tab 走到列表里。
// 焦点归还由 AssistantView 负责——触发按钮在页头，不在本组件内（与 F1 的
// MerchantSwitcher 不同，那个触发器就在组件里，所以自己归还）。
watch(
  () => props.open,
  async (open) => {
    if (!open) return
    await nextTick()
    panelElement.value?.focus()
  },
  { immediate: true },
)

async function openConversation(id: string): Promise<void> {
  await chatStore.loadConversation(id)
  emit('close')
}
</script>

<template>
  <div v-if="open" class="conversation-drawer">
    <div class="conversation-drawer__scrim" @click="emit('close')"></div>
    <section
      ref="panelElement"
      class="conversation-drawer__panel"
      role="dialog"
      aria-label="历史会话"
      data-testid="drawer-panel"
      tabindex="-1"
      @keydown.esc="emit('close')"
    >
      <header class="conversation-drawer__header">
        <h2>历史会话</h2>
        <button type="button" aria-label="关闭历史会话" @click="emit('close')">
          <X :size="16" aria-hidden="true" />
        </button>
      </header>

      <p v-if="deleteError" class="conversation-drawer__error" role="alert">{{ deleteError }}</p>

      <p v-if="chatStore.conversations.length === 0" class="conversation-drawer__empty">
        暂无历史会话。提问之后，这里会列出可以回看的会话。
      </p>

      <ul v-else class="conversation-drawer__list">
        <li
          v-for="conversation in chatStore.conversations"
          :key="conversation.id"
          data-testid="conversation-item"
        >
          <button
            class="conversation-drawer__open"
            type="button"
            data-testid="conversation-open"
            @click="openConversation(conversation.id)"
          >
            <span class="conversation-drawer__title">{{ conversation.title }}</span>
            <span class="conversation-drawer__time">{{
              new Date(conversation.updatedAt).toLocaleString('zh-CN')
            }}</span>
          </button>
          <!-- .stop 是必须的：删除按钮在会话条目内部，不拦住冒泡就会在删除的同时
               把这个会话载入当前对话。 -->
          <template v-if="pendingDeleteId === conversation.id">
            <button
              class="conversation-drawer__delete conversation-drawer__delete--confirm"
              type="button"
              data-testid="conversation-delete-confirm"
              :aria-label="`确认删除会话 ${conversation.title}`"
              @click.stop="confirmDelete(conversation.id)"
            >
              确认删除
            </button>
            <button
              class="conversation-drawer__delete"
              type="button"
              data-testid="conversation-delete-cancel"
              aria-label="取消删除"
              @click.stop="cancelDelete"
            >
              取消
            </button>
          </template>
          <button
            v-else
            class="conversation-drawer__delete"
            type="button"
            data-testid="conversation-delete"
            :aria-label="`删除会话 ${conversation.title}`"
            @click.stop="requestDelete(conversation.id)"
          >
            <Trash2 :size="15" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.conversation-drawer {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
}

.conversation-drawer__scrim {
  position: absolute;
  inset: 0;
  background: rgba(24, 32, 51, 0.28);
}

.conversation-drawer__panel {
  position: relative;
  width: min(320px, 86vw);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border-right: 1px solid var(--color-border);
  background: #fff;
  box-shadow: 0 18px 48px rgba(37, 52, 82, 0.22);
  overflow-y: auto;
}

.conversation-drawer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.conversation-drawer__header h2 {
  margin: 0;
  font-size: var(--font-size-section-title);
}

.conversation-drawer__header button {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-small);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  transition: var(--transition-colors);
}

.conversation-drawer__empty {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

.conversation-drawer__list {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.conversation-drawer__list li {
  display: flex;
  align-items: stretch;
  gap: var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-muted);
}

.conversation-drawer__open {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: var(--space-0-5);
  padding: var(--space-2) var(--space-2-5);
  border-radius: var(--radius-control);
  background: transparent;
  text-align: left;
  transition: var(--transition-colors);
}

.conversation-drawer__open:hover,
.conversation-drawer__delete:hover {
  color: var(--color-primary-strong);
  background: var(--color-primary-soft);
}

.conversation-drawer__title {
  overflow: hidden;
  color: var(--color-text);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-drawer__time {
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}

.conversation-drawer__delete {
  flex: none;
  display: grid;
  place-items: center;
  padding: 0 var(--space-2);
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  background: transparent;
  font-size: var(--font-size-caption);
  white-space: nowrap;
  transition: var(--transition-colors);
}

.conversation-drawer__delete--confirm {
  color: var(--color-danger-text);
  background: var(--color-danger-surface);
  font-weight: var(--font-weight-control);
}

.conversation-drawer__error {
  margin: 0;
  padding: var(--space-2) var(--space-2-5);
  border-radius: var(--radius-small);
  color: var(--color-danger-text);
  background: var(--color-danger-surface);
  font-size: var(--font-size-caption);
}
</style>
