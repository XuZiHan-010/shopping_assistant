<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { KnowledgeDocument } from '@/api/adapters/knowledge'
import type { UpdateKnowledgeDocumentOptions } from '@/api/knowledge'
import { useLocaleStore } from '@/stores/locale'

const props = defineProps<{
  document: KnowledgeDocument
  save?: (
    content: string,
    headers: Record<string, string>,
    options?: UpdateKnowledgeDocumentOptions,
  ) => Promise<void>
}>()

const { t } = useI18n()
const localeStore = useLocaleStore()
const content = ref(props.document.content)
const conflictMessage = ref('')
/**
 * 只有 STALE 需要用户显式确认才能继续编辑/保存——CURRENT/MISSING/SOURCE
 * 都不构成"内容可能已经不对"的风险，不需要打断。切换到另一份文档
 * （下面的 watch）会重置这个确认状态，不能带着上一份文档的确认结果。
 */
const staleAcknowledged = ref(false)

watch(
  () => props.document,
  (document) => {
    content.value = document.content
    conflictMessage.value = ''
    staleAcknowledged.value = false
  },
)

/**
 * 当前是不是在编辑源正文，而不是某一份人工译文——直接读
 * `document.translationStatus`（后端按"这次请求的 content_locale 是否等于
 * 源语言"判定出来的结果），不去比较 `localeStore.locale` 和文档的源语言
 * 猜答案。这个区分对 MISSING 状态尤其关键：请求译文但译文还不存在时，
 * 后端会回退返回源正文（`content_locale` 因此显示成源语言），如果这里改
 * 用"比较 locale 值"去判断，会把它误判成"在编辑源正文"，保存时就会把
 * 源文档覆盖成本该是译文的内容——这正是 Task 11 要收掉的坑。
 */
const isEditingSource = computed(
  () => props.document.translationStatus === undefined || props.document.translationStatus === 'SOURCE',
)
const isStale = computed(() => props.document.translationStatus === 'STALE')
const canSave = computed(() => !props.document.readOnly && (!isStale.value || staleAcknowledged.value))

async function handleConflict(): Promise<void> {
  conflictMessage.value = t('documentEditor.conflictMessage')
}

async function saveDocument(): Promise<void> {
  if (props.document.readOnly || !props.save || !canSave.value) return
  const options: UpdateKnowledgeDocumentOptions = isEditingSource.value
    ? { isSourceVersion: true }
    : { isSourceVersion: false, contentLocale: localeStore.locale }
  try {
    await props.save(content.value, { 'If-Match': `"${props.document.version}"` }, options)
  } catch (error) {
    const status =
      typeof error === 'object' && error !== null && 'status' in error ? error.status : undefined
    if (status === 412) await handleConflict()
    else throw error
  }
}

defineExpose({ handleConflict })
</script>

<template>
  <article class="document-editor">
    <header>
      <p>{{ document.path }}</p>
      <span v-if="document.readOnly">{{ t('documentEditor.memoryReadOnlyBadge') }}</span>
      <span v-else-if="!isEditingSource" data-testid="translation-badge">
        {{ t('documentEditor.translationBadge', { locale: document.contentLocale }) }}
      </span>
    </header>
    <p v-if="conflictMessage" class="document-editor__conflict" role="alert">
      {{ conflictMessage }}
    </p>
    <div v-if="isStale && !staleAcknowledged" class="document-editor__stale" role="alert">
      <p>{{ t('documentEditor.staleTranslationWarning') }}</p>
      <button type="button" data-testid="acknowledge-stale" @click="staleAcknowledged = true">
        {{ t('documentEditor.staleTranslationAcknowledge') }}
      </button>
    </div>
    <textarea
      v-model="content"
      :readonly="document.readOnly"
      :aria-label="t('documentEditor.contentAria', { path: document.path })"
    />
    <footer v-if="!document.readOnly">
      <button type="button" data-testid="save" :disabled="!canSave" @click="saveDocument">
        {{ t('documentEditor.save') }}
      </button>
    </footer>
  </article>
</template>

<style scoped>
.document-editor {
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  min-width: 0;
  padding: var(--space-4);
}

header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
}
header p {
  margin: 0;
  font-weight: var(--font-weight-control);
}
header span {
  color: var(--color-text-muted);
  font-size: var(--font-size-caption);
}
textarea {
  min-height: 25rem;
  margin-top: var(--space-4);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-small);
  resize: vertical;
  font:
    0.875rem/1.6 ui-monospace,
    SFMono-Regular,
    Consolas,
    monospace;
}
.document-editor__conflict {
  margin: var(--space-3) 0 0;
  padding: var(--space-2);
  color: var(--color-danger-text);
  background: var(--color-danger-surface);
  border-radius: var(--radius-small);
}
.document-editor__stale {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin: var(--space-3) 0 0;
  padding: var(--space-2);
  color: var(--color-danger-text);
  background: var(--color-danger-surface);
  border-radius: var(--radius-small);
}
.document-editor__stale p {
  margin: 0;
  flex: 1 1 auto;
}
footer {
  margin-top: var(--space-3);
  text-align: right;
}
button {
  min-height: var(--control-height);
  padding: 0 var(--space-4);
  border: 0;
  border-radius: var(--radius-control);
  color: white;
  background: var(--color-primary);
  font-weight: var(--font-weight-control);
}
button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
</style>
