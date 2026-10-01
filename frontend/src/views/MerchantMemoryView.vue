<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'

import { deleteMerchantMemory, fetchMerchantMemories } from '@/api/adapters/merchantMemory'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import { registerSessionScopedReset, useAuthStore } from '@/stores/auth'
import type { MerchantMemory } from '@/types/memory'

const { t } = useI18n()
const auth = useAuthStore()
const facts = ref<MerchantMemory[]>([])
const summaries = ref<MerchantMemory[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
let epoch = 0
const unregister = registerSessionScopedReset(() => {
  epoch += 1
  facts.value = []
  summaries.value = []
  nextCursor.value = null
  loading.value = false
  notice.value = ''
  error.value = ''
})
onUnmounted(unregister)

async function load(cursor?: string): Promise<void> {
  const requestEpoch = epoch
  loading.value = true
  error.value = ''
  try {
    const page = await auth.callWithSessionRetry((sid) => fetchMerchantMemories(sid, cursor))
    if (requestEpoch !== epoch) return
    facts.value = cursor ? [...facts.value, ...page.facts] : page.facts
    summaries.value = page.summaries
    nextCursor.value = page.nextCursor
  } catch {
    if (requestEpoch === epoch) error.value = t('merchantMemory.loadFailed')
  } finally {
    if (requestEpoch === epoch) loading.value = false
  }
}

async function remove(id: string): Promise<void> {
  const requestEpoch = epoch
  loading.value = true
  error.value = ''
  try {
    const result = await auth.callWithSessionRetry((sid) => deleteMerchantMemory(sid, id))
    if (requestEpoch !== epoch) return
    facts.value = facts.value.filter((item) => item.id !== id)
    if (result.summary_rebuild_scheduled) {
      notice.value = t('merchantMemory.rebuilding')
    }
    await load()
  } catch {
    if (requestEpoch === epoch) error.value = t('merchantMemory.deleteFailed')
  } finally {
    if (requestEpoch === epoch) loading.value = false
  }
}

onMounted(() => void load())
watch(() => auth.selected?.merchantId, (current, previous) => {
  if (current && previous && current !== previous) void load()
})
</script>

<template>
  <WorkspacePage title-id="page-title-memory" :title="t('merchantMemory.title')">
    <template #intro>
      <p>{{ t('merchantMemory.scope') }}</p>
    </template>
    <template #actions>
      <RouterLink class="ws-btn ws-btn--sm memory-view__back" :to="{ name: 'assistant' }">
        {{ t('merchantMemory.back') }}
      </RouterLink>
    </template>

    <div class="memory-view">
      <p v-if="error" class="ws-alert" role="alert">{{ error }}</p>
      <p v-if="notice" class="memory-view__notice" role="status">{{ notice }}</p>

      <h2 class="ws-section-title">{{ t('merchantMemory.facts') }}</h2>
      <div v-if="!loading && facts.length === 0" class="ws-panel">
        <p class="ws-state">{{ t('merchantMemory.emptyFacts') }}</p>
      </div>
      <ul class="memory-view__list">
        <li v-for="fact in facts" :key="fact.id" class="fact">
          <span class="memory-view__tag">{{ fact.category }}</span>
          <p class="fact__content">{{ fact.content }}</p>
          <div class="fact__foot">
            <RouterLink
              v-if="fact.sourceRef"
              class="ws-link fact__source"
              :to="{ name: 'assistant', query: { conversation: fact.sourceRef.conversationId } }"
            >
              {{ t('merchantMemory.source') }}
            </RouterLink>
            <button
              type="button"
              class="ws-btn ws-btn--sm ws-btn--ghost fact__delete"
              :disabled="loading"
              @click="remove(fact.id)"
            >
              {{ t('merchantMemory.delete') }}
            </button>
          </div>
        </li>
      </ul>
      <div v-if="nextCursor" class="memory-view__more">
        <button
          type="button"
          class="ws-btn ws-btn--sm"
          :disabled="loading"
          @click="load(nextCursor)"
        >
          {{ t('merchantMemory.loadMore') }}
        </button>
      </div>

      <h2 class="ws-section-title">{{ t('merchantMemory.summaries') }}</h2>
      <p class="ws-section-note memory-view__note">{{ t('merchantMemory.summaryNote') }}</p>
      <div v-if="!loading && summaries.length === 0" class="ws-panel">
        <p class="ws-state">{{ t('merchantMemory.emptySummaries') }}</p>
      </div>
      <ul class="memory-view__list memory-view__list--summaries">
        <li v-for="summary in summaries" :key="summary.id" class="summary">
          <span class="memory-view__tag">{{ summary.category }}</span>
          <p class="summary__content">{{ summary.content }}</p>
        </li>
      </ul>
    </div>
  </WorkspacePage>
</template>

<style scoped>
/*
 * 商家记忆（运营分组）：紫色标签 + 左侧紫线的事实卡片、虚线框的只读总结，
 * 与「管理」分组里铸铁绿页眉、目录树 + 编辑器的知识库明确区分（PRD M11）。
 */
.memory-view {
  overflow-wrap: anywhere;
}

.memory-view > .ws-section-title:first-of-type {
  margin-top: 4px;
}

.memory-view__notice {
  margin: 0 0 12px;
  padding: 9px 14px;
  border-radius: 10px;
  background: var(--info-soft);
  font-size: 13px;
  color: var(--info);
}

.memory-view__list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.memory-view__tag {
  align-self: flex-start;
  padding: 1px 8px;
  border-radius: 99px;
  background: var(--violet-soft);
  color: var(--violet);
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 600;
}

.fact {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--violet);
  border-radius: 12px;
  background: var(--card);
  box-shadow: var(--shadow-sm);
}

.fact__content,
.summary__content {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--ink);
}

.fact__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-top: auto;
}

.fact__source {
  margin-left: 0;
}

.fact__delete {
  margin-left: auto;
  color: var(--danger);
}

.fact__delete:hover:not(:disabled) {
  background: var(--danger-soft);
}

.memory-view__more {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}

.summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  padding: 14px 16px;
  border: 1px dashed var(--line-strong);
  border-radius: 12px;
  background: var(--well);
}

.summary__content {
  color: var(--ink-2);
}
</style>
