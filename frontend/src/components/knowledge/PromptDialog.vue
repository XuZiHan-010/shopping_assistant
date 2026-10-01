<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(
  defineProps<{
    title: string
    label: string
    placeholder?: string
    initialValue?: string
    submitLabel?: string
    errorMessage?: string
    pending?: boolean
  }>(),
  {
    placeholder: '',
    initialValue: '',
    errorMessage: '',
    pending: false,
  },
)

const { t } = useI18n()
const emit = defineEmits<{ submit: [value: string]; cancel: [] }>()
const value = ref(props.initialValue)

// `submitLabel` 的默认值不能写进 `withDefaults`——那只在组件创建时求值一次，
// 语言切换后不会重新渲染。未显式传入时改走 computed，跟随当前语言。
const resolvedSubmitLabel = computed(() => props.submitLabel ?? t('promptDialog.submitDefault'))

function submit(): void {
  const trimmed = value.value.trim()
  if (!trimmed || props.pending) return
  emit('submit', trimmed)
}
</script>

<template>
  <div class="prompt-dialog-backdrop" role="presentation" @click.self="emit('cancel')">
    <section
      class="prompt-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="prompt-dialog-title"
    >
      <h2 id="prompt-dialog-title">{{ title }}</h2>
      <form @submit.prevent="submit">
        <label for="prompt-dialog-input">{{ label }}</label>
        <input
          id="prompt-dialog-input"
          v-model="value"
          type="text"
          :placeholder="placeholder"
          autofocus
        />
        <p v-if="errorMessage" class="prompt-dialog__error" role="alert">{{ errorMessage }}</p>
        <footer>
          <button type="button" data-testid="cancel" @click="emit('cancel')">
            {{ t('promptDialog.cancel') }}
          </button>
          <button type="submit" data-testid="submit" :disabled="pending || !value.trim()">
            {{ pending ? t('promptDialog.pending') : resolvedSubmitLabel }}
          </button>
        </footer>
      </form>
    </section>
  </div>
</template>

<style scoped>
.prompt-dialog-backdrop {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(10, 16, 13, 0.4);
  z-index: 20;
}

.prompt-dialog {
  width: min(100%, 26rem);
  padding: var(--space-5);
  border: 1px solid var(--line);
  border-radius: var(--radius-column);
  background: var(--raised);
  color: var(--ink);
  box-shadow: var(--shadow-lg);
}

.prompt-dialog h2 {
  margin: 0 0 var(--space-4);
  font-family: var(--font-display);
  font-size: 19px;
  font-weight: 600;
}

footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
}

footer button {
  min-height: 34px;
  border-radius: 9px;
  padding: 0 var(--space-4);
  font: inherit;
  font-size: 13px;
  font-weight: var(--font-weight-control);
}

footer button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

footer button[data-testid='cancel'] {
  border: 1px solid var(--line-strong);
  background: var(--raised);
  color: var(--ink);
}

footer button[data-testid='cancel']:hover {
  background: var(--hover);
}

form {
  display: grid;
  gap: var(--space-2);
}

label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
}

input {
  min-height: var(--control-height);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  padding: 0 var(--space-3);
  background: var(--card);
  color: var(--ink);
  font: inherit;
}

.prompt-dialog__error {
  margin: 0;
  color: var(--danger);
}

footer {
  margin-top: var(--space-2);
}

footer button[type='submit'] {
  border: 0;
  color: var(--on-accent);
  background: var(--accent);
}

footer button[type='submit']:hover:not(:disabled) {
  background: var(--accent-strong);
}
</style>
