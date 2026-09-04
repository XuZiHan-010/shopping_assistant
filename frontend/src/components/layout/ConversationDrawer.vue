<script setup lang="ts">
import { Trash2, X } from '@lucide/vue'
import { computed, nextTick, ref, watch } from 'vue'

import { i18n } from '@/i18n'
import { useChatStore } from '@/stores/chat'
import { formatDate } from '@/utils/localizedFormat'

/**
 * 直接读全局 `i18n` 单例而不是 `useI18n()`：本组件在 `AssistantView.vue`
 * （Task 10B）里被挂载，那边不少既有测试目前还没有安装 i18n 插件；`t()`
 * 调用的 key 仍是编译期硬编码的字面量，不会丢失 `MessageSchema` 的类型
 * 校验，只是不依赖组件树注入，跟 `stores/locale.ts` 保持同一种用法。
 */
const dialogLabel = computed(() => i18n.global.t('conversationDrawer.dialogLabel'))
const drawerTitle = computed(() => i18n.global.t('conversationDrawer.title'))
const closeAria = computed(() => i18n.global.t('conversationDrawer.closeAria'))
const emptyText = computed(() => i18n.global.t('conversationDrawer.empty'))
const confirmDeleteLabel = computed(() => i18n.global.t('conversationDrawer.confirmDelete'))
const cancelDeleteAria = computed(() => i18n.global.t('conversationDrawer.cancelDeleteAria'))
const cancelDeleteLabel = computed(() => i18n.global.t('conversationDrawer.cancelDelete'))
const translationDegradedNotice = computed(() =>
  i18n.global.t('conversationDrawer.translationDegradedNotice'),
)
const retryTranslationAria = computed(() => i18n.global.t('conversationDrawer.retryTranslationAria'))
const retryTranslationLabel = computed(() =>
  i18n.global.t(
    retryingTranslation.value
      ? 'conversationDrawer.retryingTranslation'
      : 'conversationDrawer.retryTranslation',
  ),
)

function confirmDeleteAria(conversationTitle: string): string {
  return i18n.global.t('conversationDrawer.confirmDeleteAria', { title: conversationTitle })
}

function deleteAria(conversationTitle: string): string {
  return i18n.global.t('conversationDrawer.deleteAria', { title: conversationTitle })
}

function formatUpdatedAt(updatedAt: string): string {
  return formatDate(updatedAt, i18n.global.locale.value)
}

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
    deleteError.value = i18n.global.t('conversationDrawer.deleteFailed')
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

/**
 * 历史重试入口（Task 10B 遗留缺口，本任务落地）：会话列表接口返回
 * `localization_degraded: true` 时，本页至少一条会话标题没能在预算内翻译
 * 完成、改用了目标语言的占位文案（R7）。这个按钮原样重新 GET 同一页
 * （`limit`/`offset` 不变），已经翻译成功的条目命中缓存，只有仍然缺失的
 * 部分有机会补上——不是"刷新列表"这种更宽泛的操作。
 */
const retryingTranslation = ref(false)

async function retryTranslation(): Promise<void> {
  if (retryingTranslation.value) return
  retryingTranslation.value = true
  try {
    await chatStore.loadConversations()
  } finally {
    retryingTranslation.value = false
  }
}
</script>

<template>
  <div v-if="open" class="conversation-drawer">
    <div class="conversation-drawer__scrim" @click="emit('close')"></div>
    <section
      ref="panelElement"
      class="conversation-drawer__panel"
      role="dialog"
      :aria-label="dialogLabel"
      data-testid="drawer-panel"
      tabindex="-1"
      @keydown.esc="emit('close')"
    >
      <header class="conversation-drawer__header">
        <h2>{{ drawerTitle }}</h2>
        <button type="button" :aria-label="closeAria" @click="emit('close')">
          <X :size="16" aria-hidden="true" />
        </button>
      </header>

      <p v-if="deleteError" class="conversation-drawer__error" role="alert">{{ deleteError }}</p>

      <div
        v-if="chatStore.conversationsLocalizationDegraded"
        class="conversation-drawer__translation-notice"
        role="status"
      >
        <span>{{ translationDegradedNotice }}</span>
        <button
          type="button"
          data-testid="retry-translation"
          :aria-label="retryTranslationAria"
          :disabled="retryingTranslation"
          @click="retryTranslation"
        >
          {{ retryTranslationLabel }}
        </button>
      </div>

      <p v-if="chatStore.conversations.length === 0" class="conversation-drawer__empty">
        {{ emptyText }}
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
              formatUpdatedAt(conversation.updatedAt)
            }}</span>
          </button>
          <!-- .stop 是必须的：删除按钮在会话条目内部，不拦住冒泡就会在删除的同时
               把这个会话载入当前对话。 -->
          <template v-if="pendingDeleteId === conversation.id">
            <button
              class="conversation-drawer__delete conversation-drawer__delete--confirm"
              type="button"
              data-testid="conversation-delete-confirm"
              :aria-label="confirmDeleteAria(conversation.title)"
              @click.stop="confirmDelete(conversation.id)"
            >
              {{ confirmDeleteLabel }}
            </button>
            <button
              class="conversation-drawer__delete"
              type="button"
              data-testid="conversation-delete-cancel"
              :aria-label="cancelDeleteAria"
              @click.stop="cancelDelete"
            >
              {{ cancelDeleteLabel }}
            </button>
          </template>
          <button
            v-else
            class="conversation-drawer__delete"
            type="button"
            data-testid="conversation-delete"
            :aria-label="deleteAria(conversation.title)"
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

.conversation-drawer__translation-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-2) var(--space-2-5);
  border-radius: var(--radius-small);
  color: var(--color-text-secondary);
  background: var(--color-surface-muted);
  font-size: var(--font-size-caption);
}

.conversation-drawer__translation-notice button {
  flex: none;
  padding: var(--space-0-5) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-primary-strong);
  background: var(--color-surface);
  font-size: var(--font-size-caption);
  white-space: nowrap;
}

.conversation-drawer__translation-notice button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
</style>
