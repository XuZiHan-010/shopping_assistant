<script setup lang="ts">
/**
 * v2 运营助手的会话目录侧栏（PRD §12.4：新建、浏览、跳转、删除）。
 *
 * 只负责展示与发出意图；数据、归属与删除后的状态收敛都在 `stores/opsChat.ts`。
 * 列表顺序原样沿用服务端（`updated_at DESC`），这里不排序、不过滤。
 */
import { useI18n } from 'vue-i18n'

import type { MerchantConversationSummary } from '@/api/adapters/merchantConversations'
import type { DirectoryStatus } from '@/stores/opsChat'
import { useLocaleStore } from '@/stores/locale'
import { formatDate } from '@/utils/localizedFormat'

defineProps<{
  items: MerchantConversationSummary[]
  currentId: string | null
  status: DirectoryStatus
  hasMore: boolean
  disabled: boolean
}>()

const emit = defineEmits<{
  open: [id: string]
  remove: [id: string]
  create: []
  loadMore: []
  retry: []
}>()

const { t } = useI18n()
const localeStore = useLocaleStore()
</script>

<template>
  <section class="ops-directory" :aria-label="t('opsAssistant.directoryTitle')">
    <div class="ops-directory__header">
      <h2 class="ops-directory__title">{{ t('opsAssistant.directoryTitle') }}</h2>
      <button type="button" class="ops-button" :disabled="disabled" @click="emit('create')">
        {{ t('opsAssistant.newConversation') }}
      </button>
    </div>

    <div v-if="status === 'failed'" class="ops-directory__notice">
      <span>{{ t('opsAssistant.directoryLoadFailed') }}</span>
      <button type="button" class="ops-button" @click="emit('retry')">
        {{ t('opsAssistant.retry') }}
      </button>
    </div>
    <p v-else-if="status === 'ready' && items.length === 0" class="ops-directory__notice">
      {{ t('opsAssistant.directoryEmpty') }}
    </p>

    <ul class="ops-directory__list">
      <li
        v-for="item in items"
        :key="item.id"
        class="ops-directory__item"
        data-test="ops-conversation-item"
      >
        <button
          type="button"
          class="ops-directory__open"
          data-test="ops-conversation-open"
          :aria-current="item.id === currentId ? 'true' : undefined"
          :disabled="disabled"
          @click="emit('open', item.id)"
        >
          <span class="ops-directory__item-title">{{ item.title }}</span>
          <span class="ops-directory__item-time">{{
            formatDate(item.updatedAt, localeStore.locale)
          }}</span>
        </button>
        <button
          type="button"
          class="ops-button"
          data-test="ops-conversation-delete"
          :aria-label="t('opsAssistant.deleteLabel', { title: item.title })"
          :disabled="disabled"
          @click="emit('remove', item.id)"
        >
          {{ t('opsAssistant.delete') }}
        </button>
      </li>
    </ul>

    <button
      v-if="hasMore"
      type="button"
      class="ops-button"
      :disabled="disabled"
      @click="emit('loadMore')"
    >
      {{ t('opsAssistant.loadMore') }}
    </button>
  </section>
</template>

<style scoped>
.ops-directory {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
}
.ops-directory__header {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}
.ops-directory__title {
  margin: 0;
  font-size: var(--font-size-section-title);
}
.ops-directory__notice {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
  color: var(--ink-2);
  font-size: var(--font-size-caption);
}
.ops-directory__list {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 24rem;
  overflow-y: auto;
}
.ops-directory__item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-2);
  align-items: center;
}
.ops-directory__open {
  display: grid;
  min-width: 0;
  padding: var(--space-1-5) var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--ink);
  text-align: left;
  cursor: pointer;
}
.ops-directory__open[aria-current='true'] {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.ops-directory__item-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ops-directory__item-time {
  color: var(--ink-2);
  font-size: var(--font-size-caption);
}
.ops-button {
  min-height: var(--control-height);
  padding: 0 var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--card);
  color: var(--ink);
  cursor: pointer;
}
.ops-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 40rem) {
  .ops-directory__list {
    max-height: 12rem;
  }
}
</style>
