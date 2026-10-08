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
const viewerToken = resolveViewerToken()
// 配置了只读令牌就默认勾选：访客不用输入任何东西即可只读浏览；要编辑的人取消勾选
// 再输入管理员令牌。只读令牌本身可公开（R6），所以允许预填并明文显示。
const useViewerToken = ref(Boolean(viewerToken))
const token = ref(viewerToken ?? '')

const instructions = computed(() =>
  viewerToken ? t('adminTokenDialog.instructionsWithViewer') : t('adminTokenDialog.instructions'),
)

function toggleViewerToken(checked: boolean): void {
  useViewerToken.value = checked
  token.value = checked ? (viewerToken ?? '') : ''
}

function submit(): void {
  if (!token.value.trim()) return
  emit('submit', token.value.trim())
  // 回到初始状态，手输的管理员令牌不留在输入框里。
  toggleViewerToken(Boolean(viewerToken))
}
</script>

<template>
  <section class="admin-token-dialog" role="dialog" aria-labelledby="admin-token-title">
    <p class="admin-token-dialog__eyebrow">{{ resolvedEyebrow }}</p>
    <h1 id="admin-token-title">{{ resolvedTitle }}</h1>
    <p>{{ instructions }}</p>
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
  margin: 8vh auto;
  padding: 2rem;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-column);
  background: var(--card);
  color: var(--ink);
  box-shadow: var(--shadow);
}
.admin-token-dialog__eyebrow {
  margin: 0 0 var(--space-2);
  color: var(--gilt-ink);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-title);
  letter-spacing: 0.12em;
}
h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.6rem;
  font-weight: 600;
  letter-spacing: -0.015em;
}
p {
  color: var(--ink-2);
}
form {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-5);
}
label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
}
input,
button {
  min-height: var(--control-height);
  border-radius: var(--radius-control);
  font: inherit;
}
input {
  border: 1px solid var(--line-strong);
  padding: 0 var(--space-3);
  background: var(--raised);
  color: var(--ink);
}
.admin-token-dialog__viewer-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink-2);
  font-size: var(--font-size-caption);
  font-weight: 400;
}
.admin-token-dialog__viewer-toggle input {
  min-height: 0;
  width: auto;
  accent-color: var(--accent);
}
button {
  border: 0;
  color: var(--on-accent);
  background: var(--accent);
  font-weight: var(--font-weight-control);
}
button:hover {
  background: var(--accent-strong);
}
@media (max-width: 520px) {
  .admin-token-dialog {
    margin: 2rem auto;
    padding: 1.25rem;
  }
}
</style>
