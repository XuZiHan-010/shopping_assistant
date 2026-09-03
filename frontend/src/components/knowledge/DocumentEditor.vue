<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { KnowledgeDocument } from '@/api/adapters/knowledge'

const props = defineProps<{
  document: KnowledgeDocument
  save?: (content: string, headers: Record<string, string>) => Promise<void>
}>()

const { t } = useI18n()
const content = ref(props.document.content)
const conflictMessage = ref('')

watch(
  () => props.document,
  (document) => {
    content.value = document.content
    conflictMessage.value = ''
  },
)

async function handleConflict(): Promise<void> {
  conflictMessage.value = t('documentEditor.conflictMessage')
}

async function saveDocument(): Promise<void> {
  if (props.document.readOnly || !props.save) return
  try {
    await props.save(content.value, { 'If-Match': `"${props.document.version}"` })
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
    </header>
    <p v-if="conflictMessage" class="document-editor__conflict" role="alert">
      {{ conflictMessage }}
    </p>
    <textarea
      v-model="content"
      :readonly="document.readOnly"
      :aria-label="t('documentEditor.contentAria', { path: document.path })"
    />
    <footer v-if="!document.readOnly">
      <button type="button" data-testid="save" @click="saveDocument">
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
</style>
