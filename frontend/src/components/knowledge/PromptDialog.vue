<script setup lang="ts">
import { ref } from 'vue'

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
    submitLabel: '确认',
    errorMessage: '',
    pending: false,
  },
)

const emit = defineEmits<{ submit: [value: string]; cancel: [] }>()
const value = ref(props.initialValue)

function submit(): void {
  const trimmed = value.value.trim()
  if (!trimmed || props.pending) return
  emit('submit', trimmed)
}
</script>

<template>
  <div class="prompt-dialog-backdrop" role="presentation" @click.self="emit('cancel')">
    <section class="prompt-dialog" role="dialog" aria-modal="true" aria-labelledby="prompt-dialog-title">
      <h2 id="prompt-dialog-title">{{ title }}</h2>
      <form @submit.prevent="submit">
        <label for="prompt-dialog-input">{{ label }}</label>
        <input id="prompt-dialog-input" v-model="value" type="text" :placeholder="placeholder" autofocus />
        <p v-if="errorMessage" class="prompt-dialog__error" role="alert">{{ errorMessage }}</p>
        <footer>
          <button type="button" data-testid="cancel" @click="emit('cancel')">取消</button>
          <button type="submit" data-testid="submit" :disabled="pending || !value.trim()">
            {{ pending ? '处理中…' : submitLabel }}
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
  background: rgba(15, 23, 42, 0.4);
  z-index: 20;
}

.prompt-dialog {
  width: min(90vw, 26rem);
  padding: var(--space-5);
  border-radius: var(--radius-column);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.prompt-dialog h2 {
  margin: 0 0 var(--space-4);
}

form {
  display: grid;
  gap: var(--space-2);
}

input {
  min-height: var(--control-height);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  padding: 0 var(--space-3);
  font: inherit;
}

.prompt-dialog__error {
  margin: 0;
  color: var(--color-danger-text);
}

footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

footer button {
  min-height: var(--control-height);
  border-radius: var(--radius-control);
  padding: 0 var(--space-4);
  font: inherit;
}

footer button[type='submit'] {
  border: 0;
  color: white;
  background: var(--color-primary);
  font-weight: var(--font-weight-control);
}

footer button[type='button'] {
  border: 1px solid var(--color-border);
  background: white;
}
</style>
