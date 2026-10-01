<script setup lang="ts">
/**
 * 「管理」分组的令牌闸门（W Task 7，设计说明 §2.1：管理分组进入须管理员令牌，权限不变）。
 *
 * - 没有令牌：只渲染令牌入口（复用 `AdminTokenDialog`），**不发任何 `/api/admin/*` 请求**，
 *   也不渲染插槽里的受保护内容；
 * - 提交令牌：先用它拉一次知识目录树验证；被拒绝就清掉令牌、留在入口并提示错误；
 * - 通过后渲染插槽。已持令牌的重新挂载（切商家、路由往返）会静默重验一次。
 *
 * 令牌只存在 `useKnowledgeStore().adminToken`（内存 Pinia 状态，`main.ts` 的凭证 provider
 * 在请求瞬间读取），不进 URL、localStorage 或日志。管理员令牌只走 `X-Admin-Token`，
 * 与商家会话凭证（`Authorization` / `X-Session-Id`）互不混用，见 `api/credentials.ts`。
 *
 * N5 的运维看板（`OpsStatusView`）也放「管理」分组，届时同样包一层本组件即可；
 * 本 Task 不创建该页面。
 *
 * 语言切换不在本组件里（W Task 10）：外壳偏好设置随时可切；知识库页在闸门之外放了
 * 全页唯一的一个 `LanguageSwitcher`，授权前后都可用。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import AdminTokenDialog from '@/components/knowledge/AdminTokenDialog.vue'
import { useKnowledgeStore } from '@/stores/knowledge'

const { t } = useI18n()
const knowledgeStore = useKnowledgeStore()
const authorizationError = ref('')
/** 本次令牌是否已被后端验证通过；验证完成前不渲染受保护内容，坏令牌不会闪一下知识库。 */
const verified = ref(false)
const verifying = ref(false)
/** 非 401/403 的失败（网络、5xx）：令牌保留，给出可重试的提示。 */
const retryError = ref('')

async function verify(): Promise<void> {
  verifying.value = true
  retryError.value = ''
  try {
    await knowledgeStore.loadTree()
    verified.value = true
  } catch (error) {
    const status =
      typeof error === 'object' && error !== null && 'status' in error
        ? (error as { status?: number }).status
        : undefined
    if (status === 401 || status === 403) {
      authorizationError.value =
        error instanceof Error ? error.message : t('adminGate.tokenRejected')
      knowledgeStore.signOut()
    } else {
      retryError.value = t('adminGate.verifyFailedRetry')
    }
  } finally {
    verifying.value = false
  }
}

async function authorize(token: string): Promise<void> {
  authorizationError.value = ''
  verified.value = false
  knowledgeStore.setAdminToken(token)
  await verify()
}

onMounted(() => {
  if (knowledgeStore.adminToken) void verify()
})
</script>

<template>
  <slot v-if="knowledgeStore.adminToken && verified" />
  <div v-else-if="knowledgeStore.adminToken" class="admin-gate">
    <p v-if="retryError" role="alert" data-testid="admin-gate-retry-error">{{ retryError }}</p>
    <button v-if="retryError" type="button" data-testid="admin-gate-retry" @click="verify">
      {{ t('adminGate.retry') }}
    </button>
    <p v-else role="status" data-testid="admin-gate-verifying">{{ t('adminGate.verifying') }}</p>
  </div>
  <div v-else class="admin-gate">
    <AdminTokenDialog @submit="authorize" />
    <p v-if="authorizationError" class="admin-gate__error" role="alert">
      {{ authorizationError }}
    </p>
  </div>
</template>

<style scoped>
.admin-gate > p,
.admin-gate > button {
  display: block;
  width: min(100%, 31rem);
  margin: var(--space-4) auto 0;
  font-size: 13px;
  color: var(--ink-2);
}

.admin-gate > p[role='alert'] {
  color: var(--danger);
}

.admin-gate > button {
  width: auto;
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--raised);
  font-weight: 600;
  color: var(--ink);
}

.admin-gate > button:hover {
  background: var(--hover);
}

.admin-gate__error {
  width: min(100%, 31rem);
  margin: calc(-1 * var(--space-6)) auto 0;
  color: var(--danger);
}
</style>
