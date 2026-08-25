<script setup lang="ts">
withDefaults(
  defineProps<{
    name: string
    path: string
    isDomain?: boolean
    errorMessage?: string
    pending?: boolean
  }>(),
  {
    isDomain: false,
    errorMessage: '',
    pending: false,
  },
)

const emit = defineEmits<{ confirm: []; cancel: [] }>()
</script>

<template>
  <div class="confirm-delete-backdrop" role="presentation" @click.self="emit('cancel')">
    <section
      class="confirm-delete-dialog"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-delete-title"
    >
      <h2 id="confirm-delete-title">删除知识节点</h2>
      <p class="confirm-delete-dialog__target">
        <strong>{{ name }}</strong>
        <span>{{ path }}</span>
      </p>
      <p v-if="isDomain" class="confirm-delete-dialog__warning">
        该业务域及其全部文档将被级联删除，此操作不可撤销。
      </p>
      <p v-else class="confirm-delete-dialog__warning">该文档将被删除，此操作不可撤销。</p>
      <p v-if="errorMessage" class="confirm-delete-dialog__error" role="alert">{{ errorMessage }}</p>
      <footer>
        <button type="button" data-testid="cancel" @click="emit('cancel')">取消</button>
        <button type="button" data-testid="confirm" :disabled="pending" @click="emit('confirm')">
          {{ pending ? '删除中…' : '确认删除' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.confirm-delete-backdrop {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(15, 23, 42, 0.4);
  z-index: 20;
}

.confirm-delete-dialog {
  width: min(90vw, 26rem);
  padding: var(--space-5);
  border-radius: var(--radius-column);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.confirm-delete-dialog h2 {
  margin: 0 0 var(--space-3);
}

.confirm-delete-dialog__target {
  display: grid;
  gap: var(--space-1);
  margin: 0 0 var(--space-3);
}

.confirm-delete-dialog__target span {
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}

.confirm-delete-dialog__warning {
  margin: 0 0 var(--space-3);
  color: var(--color-text-secondary);
}

.confirm-delete-dialog__error {
  margin: 0 0 var(--space-3);
  color: var(--color-danger-text);
}

footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

footer button {
  min-height: var(--control-height);
  border-radius: var(--radius-control);
  padding: 0 var(--space-4);
  font: inherit;
}

footer button[data-testid='confirm'] {
  border: 0;
  color: white;
  background: var(--color-danger-text);
  font-weight: var(--font-weight-control);
}

footer button[data-testid='cancel'] {
  border: 1px solid var(--color-border);
  background: white;
}
</style>
