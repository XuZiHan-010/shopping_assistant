<script setup lang="ts">
/**
 * 最小当日简报 + 待批准草稿（PRD §15 N2 裁定：S3 用确定性最小简报闭环，
 * 完整 M2 留 N3）。简报来源如实标注为确定性规则，**界面不得出现"AI 分析"字样**（R7）。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import {
  fetchDailyBrief,
  regenerateDailyBrief,
  type DailyBrief,
} from '@/api/adapters/merchantOps'
import { AppError } from '@/api/errors'
import { useAuthStore } from '@/stores/auth'
import { useDraftsStore } from '@/stores/drafts'
import { useLocaleStore } from '@/stores/locale'
import { useOpsChatStore } from '@/stores/opsChat'
import { formatDate } from '@/utils/localizedFormat'

/**
 * 与后端 `REGENERATE_COOLDOWN_SECONDS`（`app/services/v2/daily_brief.py`）保持一致——
 * 按钮的禁用状态只是提前给出的界面提示，真正的限制在服务端强制；两边数值不一致时
 * 顶多是按钮提前几秒可点、点击后端仍会 429，不构成安全问题。
 */
const REGENERATE_COOLDOWN_SECONDS = 60

const emit = defineEmits<{ 'fill-input': [text: string] }>()

const auth = useAuthStore()
const draftsStore = useDraftsStore()
const localeStore = useLocaleStore()
const opsChat = useOpsChatStore()
const router = useRouter()
const { t } = useI18n()

const brief = ref<DailyBrief | undefined>(undefined)
const loading = ref(false)
const errorMessage = ref('')
const regenerating = ref(false)
const regenerateErrorMessage = ref('')
/** 每秒刷新一次「现在」，让冷却结束后按钮自动变回可点，不需要商家手动刷新页面。 */
const now = ref(Date.now())
let cooldownTimer: ReturnType<typeof setInterval> | undefined

async function load(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [loadedBrief] = await Promise.all([
      auth.callWithSessionRetry((sid) => fetchDailyBrief(sid)),
      draftsStore.loadDrafts({ state: 'STAGED' }),
    ])
    brief.value = loadedBrief
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('todayView.loadFailed')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  cooldownTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (cooldownTimer !== undefined) clearInterval(cooldownTimer)
})

/**
 * 与后端同一条规则（`app/api/routes/v2/merchant_brief.py`）：只有真正的
 * `REGENERATED` 触发才计入冷却，`GET` 的隐式首次生成（`SCHEDULED`）不消耗冷却额度。
 */
const inCooldown = computed(() => {
  if (!brief.value || brief.value.trigger !== 'REGENERATED') return false
  const elapsedMs = now.value - new Date(brief.value.generatedAt).getTime()
  return elapsedMs < REGENERATE_COOLDOWN_SECONDS * 1000
})

const canRegenerate = computed(() => !regenerating.value && !inCooldown.value)

async function regenerate(): Promise<void> {
  if (!canRegenerate.value) return
  regenerating.value = true
  regenerateErrorMessage.value = ''
  const clientRequestId = `regen-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  try {
    brief.value = await auth.callWithSessionRetry((sid) =>
      regenerateDailyBrief(sid, clientRequestId),
    )
  } catch (error) {
    if (error instanceof AppError && error.code === 'RATE_LIMITED') {
      regenerateErrorMessage.value = t('todayView.regenerateCooldownActive')
    } else {
      regenerateErrorMessage.value =
        error instanceof Error ? error.message : t('todayView.regenerateFailed')
    }
  } finally {
    regenerating.value = false
  }
}

const pendingDrafts = computed(() => draftsStore.items)

/**
 * 只把问题填进输入框，不代为发送、批准或执行（D18④）。事件留给嵌入本组件的外壳；
 * 作为独立页面时，把问题预填到运营助手（`/`）并跳过去，由商家自己决定是否发送。
 */
function fillInput(prompt: string): void {
  emit('fill-input', prompt)
  opsChat.prefill(prompt)
  void router.push({ name: 'assistant' })
}
</script>

<template>
  <section class="today-view">
    <h1>{{ t('todayView.title') }}</h1>

    <p v-if="loading">{{ t('todayView.loading') }}</p>
    <p v-else-if="errorMessage" role="alert">{{ errorMessage }}</p>

    <template v-else-if="brief">
      <p class="today-view__timestamps">
        {{ t('todayView.dataAsOf') }}：{{ formatDate(brief.dataAsOf, localeStore.locale) }} ·
        {{ t('todayView.generatedAt') }}：{{ formatDate(brief.generatedAt, localeStore.locale) }} ·
        {{ t('todayView.briefVersion', { version: brief.briefVersion }) }}
      </p>
      <p v-if="brief.degraded" role="status">{{ t('todayView.degradedNotice') }}</p>

      <button
        type="button"
        data-test="regenerate"
        :disabled="!canRegenerate"
        @click="regenerate"
      >
        {{ regenerating ? t('todayView.regenerating') : t('todayView.regenerate') }}
      </button>
      <p v-if="regenerateErrorMessage" role="alert">{{ regenerateErrorMessage }}</p>

      <ul class="today-view__items">
        <li v-for="item in brief.items" :key="item.rank">
          <p>{{ item.title }}</p>
          <p>{{ item.evidence }}</p>
          <button
            v-if="item.nextActionPrompt"
            data-test="next-action"
            type="button"
            @click="fillInput(item.nextActionPrompt)"
          >
            {{ item.nextActionPrompt }}
          </button>
        </li>
      </ul>
      <p v-if="brief.collapsedCount > 0">
        {{ t('todayView.collapsedCount', { count: brief.collapsedCount }) }}
      </p>
    </template>

    <h2>{{ t('todayView.pendingDraftsTitle') }}</h2>
    <p v-if="pendingDrafts.length === 0">{{ t('todayView.pendingDraftsEmpty') }}</p>
    <ul v-else class="today-view__pending-drafts">
      <li v-for="draft in pendingDrafts" :key="draft.id">
        {{ draft.title }}
        <router-link :to="{ name: 'approval', params: { draftId: draft.id } }">
          {{ t('todayView.goToApprove') }}
        </router-link>
      </li>
    </ul>
  </section>
</template>
