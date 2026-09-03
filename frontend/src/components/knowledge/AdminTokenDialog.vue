<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { resolveViewerToken } from '@/api/client'

const props = defineProps<{
  title?: string
  eyebrow?: string
}>()

const { t } = useI18n()

// 与 `PromptDialog.vue` 同样的原因：默认值不能写进 `withDefaults`，否则语言
// 切换后不会重新渲染，只能靠 computed 在未显式传入时跟随当前语言。
const resolvedTitle = computed(() => props.title ?? t('adminTokenDialog.title'))
const resolvedEyebrow = computed(() => props.eyebrow ?? t('adminTokenDialog.eyebrow'))

const emit = defineEmits<{ submit: [token: string] }>()
const token = ref('')
const useViewerToken = ref(false)
const viewerToken = resolveViewerToken()

function toggleViewerToken(checked: boolean): void {
  useViewerToken.value = checked
  token.value = checked ? (viewerToken ?? '') : ''
}

function submit(): void {
  if (!token.value.trim()) return
  emit('submit', token.value.trim())
  token.value = ''
  useViewerToken.value = false
}
</script>

<template>
  <section
    class="admin-token-dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="admin-token-title"
  >
    <p class="admin-token-dialog__eyebrow">{{ resolvedEyebrow }}</p>
    <h1 id="admin-token-title">{{ resolvedTitle }}</h1>
    <p>{{ t('adminTokenDialog.instructions') }}</p>
    <form @submit.prevent="submit">
      <label for="admin-token">{{ t('adminTokenDialog.tokenLabel') }}</label>
      <input
        id="admin-token"
        v-model="token"
        data-testid="admin-token-input"
        :type="useViewerToken ? 'text' : 'password'"
        :readonly="useViewerToken"
        autocomplete="off"
        required
      />
      <label v-if="viewerToken" class="admin-token-dialog__viewer-toggle">
        <input
          type="checkbox"
          data-testid="use-viewer-token"
          :checked="useViewerToken"
          @change="toggleViewerToken(($event.target as HTMLInputElement).checked)"
        />
        {{ t('adminTokenDialog.viewerToggleLabel') }}
      </label>
      <button type="submit">{{ t('adminTokenDialog.submit') }}</button>
    </form>
  </section>
</template>

<style scoped>
.admin-token-dialog {
  width: min(100%, 31rem);
  margin: 10vh auto;
  padding: 2.25rem;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-column);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}
.admin-token-dialog__eyebrow {
  margin: 0 0 var(--space-2);
  color: var(--color-teal);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-title);
  letter-spacing: 0.12em;
}
h1 {
  margin: 0;
  font-size: 1.6rem;
}
p {
  color: var(--color-text-secondary);
}
form {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-5);
}
input,
button {
  min-height: var(--control-height);
  border-radius: var(--radius-control);
  font: inherit;
}
input {
  border: 1px solid var(--color-border-strong);
  padding: 0 var(--space-3);
}
.admin-token-dialog__viewer-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}
.admin-token-dialog__viewer-toggle input {
  min-height: 0;
  width: auto;
}
button {
  border: 0;
  color: white;
  background: var(--color-primary);
  font-weight: var(--font-weight-control);
}
</style>
