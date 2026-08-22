<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{ submit: [token: string] }>()
const token = ref('')

function submit(): void {
  if (!token.value.trim()) return
  emit('submit', token.value.trim())
  token.value = ''
}
</script>

<template>
  <section class="admin-token-dialog" aria-labelledby="admin-token-title">
    <p class="admin-token-dialog__eyebrow">BOROUGH · KNOWLEDGE OPS</p>
    <h1 id="admin-token-title">知识库维护后台</h1>
    <p>请输入管理员令牌后继续。令牌仅保留在当前页面内存中。</p>
    <form @submit.prevent="submit">
      <label for="admin-token">管理员令牌</label>
      <input id="admin-token" v-model="token" type="password" autocomplete="off" required />
      <button type="submit">进入后台</button>
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
button {
  border: 0;
  color: white;
  background: var(--color-primary);
  font-weight: var(--font-weight-control);
}
</style>
