<script setup lang="ts">
/**
 * 首页「今日简报」卡（W Task 8；逻辑迁自已删除的 `TodayView.vue`）。
 *
 * - 简报是确定性规则汇总（PRD §15 N2、设计说明 §4.2），**界面不得写成“AI 分析”**（R7）；
 *   逐条渲染 `items` 的 `title` 与 `evidence`，不拼成一段假装模型写的话；`degraded` 为真时显示降级说明。
 * - 条目的「问助手」用 `nextActionPrompt`：经 `rail.ask()` 只预填并打开助手栏，不发送、不跳页（D18④）。
 * - 截至时间、生成时间、版本、重新生成与冷却行为沿用 `TodayView`。
 * - 「去审批（N）」合并在简报按钮里，N 来自草稿 Store（`STAGED` 首页）；草稿列表失败只影响这一个入口。
 * - 取数推迟到浏览器空闲之后（`whenIdle`），首屏请求序列保持不变（`e2e/first-paint.spec.ts`）。
 */
import { Sparkles, Stamp } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { fetchDailyBrief, regenerateDailyBrief, type DailyBrief } from '@/api/adapters/merchantOps'
import { AppError } from '@/api/errors'
import { useAuthStore } from '@/stores/auth'
import { useDraftsStore } from '@/stores/drafts'
import { useLocaleStore } from '@/stores/locale'
import { useRailStore } from '@/stores/rail'
import { whenIdle } from '@/utils/idle'
import { formatDate } from '@/utils/localizedFormat'

/**
 * 与后端 `REGENERATE_COOLDOWN_SECONDS`（`app/services/v2/daily_brief.py`）保持一致——
 * 按钮的禁用状态只是提前给出的界面提示，真正的限制在服务端强制；两边数值不一致时
 * 顶多是按钮提前几秒可点、点击后端仍会 429，不构成安全问题。
 */
const REGENERATE_COOLDOWN_SECONDS = 60

const auth = useAuthStore()
const draftsStore = useDraftsStore()
const localeStore = useLocaleStore()
const rail = useRailStore()
const { t } = useI18n()

const brief = ref<DailyBrief | undefined>(undefined)
const loading = ref(true)
const errorMessage = ref('')
const draftsStatus = ref<'loading' | 'ready' | 'error'>('loading')
const regenerating = ref(false)
const regenerateErrorMessage = ref('')
/** 每秒刷新一次「现在」，让冷却结束后按钮自动变回可点，不需要商家手动刷新页面。 */
const now = ref(Date.now())
let cooldownTimer: ReturnType<typeof setInterval> | undefined
let cancelIdle: (() => void) | undefined

async function loadBrief(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    brief.value = await auth.callWithSessionRetry((sid) => fetchDailyBrief(sid))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('home.brief.loadFailed')
  } finally {
    loading.value = false
  }
}

async function loadDrafts(): Promise<void> {
  draftsStatus.value = 'loading'
  try {
    await draftsStore.loadDrafts({ state: 'STAGED' })
    draftsStatus.value = 'ready'
  } catch {
    draftsStatus.value = 'error'
  }
}

onMounted(() => {
  cancelIdle = whenIdle(() => {
    void loadBrief()
    void loadDrafts()
  })
  cooldownTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  cancelIdle?.()
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
      regenerateErrorMessage.value = t('home.brief.regenerateCooldownActive')
    } else {
      regenerateErrorMessage.value =
        error instanceof Error ? error.message : t('home.brief.regenerateFailed')
    }
  } finally {
    regenerating.value = false
  }
}

/** 草稿只取了第一页：还有下一页时写成「20+」，不把一页的条数当成总数。 */
const pendingCount = computed(() => {
  const count = draftsStore.items.length
  return draftsStore.hasMore ? `${count}+` : String(count)
})
const hasPendingDrafts = computed(() => draftsStore.items.length > 0)

function ask(prompt: string): void {
  rail.ask(prompt)
}
</script>

<template>
  <section class="brief" data-test="home-brief" aria-labelledby="home-brief-title">
    <div class="brief__body">
      <header class="brief__head">
        <h2 id="home-brief-title" class="brief__title">{{ t('home.brief.title') }}</h2>
        <p v-if="brief" class="brief__meta">
          {{ t('home.brief.generatedAt') }}
          {{ formatDate(brief.generatedAt, localeStore.locale) }} · {{ t('home.brief.dataAsOf') }}
          {{ formatDate(brief.dataAsOf, localeStore.locale) }} ·
          {{ t('home.brief.version', { version: brief.briefVersion }) }}
        </p>
      </header>

      <p v-if="loading" class="brief__status">{{ t('home.brief.loading') }}</p>
      <div v-else-if="errorMessage" class="brief__status" role="alert">
        <span>{{ t('home.brief.loadFailed') }}</span>
        <button type="button" class="brief__link" @click="loadBrief">
          {{ t('home.brief.retry') }}
        </button>
      </div>

      <template v-else-if="brief">
        <p v-if="brief.degraded" class="brief__degraded" role="status" data-test="brief-degraded">
          {{
            brief.degradedReason
              ? t('home.brief.degraded', { reason: brief.degradedReason })
              : t('home.brief.degradedNoReason')
          }}
        </p>

        <ol v-if="brief.items.length > 0" class="brief__items">
          <li
            v-for="item in brief.items"
            :key="item.rank"
            data-test="brief-item"
            class="brief__item"
          >
            <p class="brief__item-title" data-test="brief-item-title">{{ item.title }}</p>
            <p class="brief__item-evidence" data-test="brief-item-evidence">{{ item.evidence }}</p>
            <button
              v-if="item.nextActionPrompt"
              type="button"
              class="brief__ask"
              data-test="next-action"
              :aria-label="t('home.brief.askAria', { prompt: item.nextActionPrompt })"
              @click="ask(item.nextActionPrompt)"
            >
              <Sparkles :size="13" aria-hidden="true" />{{ item.nextActionPrompt }}
            </button>
          </li>
        </ol>
        <p v-else class="brief__status">{{ t('home.brief.empty') }}</p>

        <p v-if="brief.collapsedCount > 0" class="brief__collapsed">
          {{ t('home.brief.collapsedCount', { count: brief.collapsedCount }) }}
        </p>
        <p class="brief__source">{{ t('home.brief.sourceNote') }}</p>
      </template>
    </div>

    <div class="brief__actions">
      <RouterLink
        v-if="draftsStatus === 'ready' && hasPendingDrafts"
        class="btn btn--primary"
        data-test="go-approve"
        :to="{ name: 'approval-list' }"
      >
        <Stamp :size="15" aria-hidden="true" />{{
          t('home.brief.goApprove', { count: pendingCount })
        }}
      </RouterLink>
      <p v-else-if="draftsStatus === 'ready'" class="brief__hint">
        {{ t('home.brief.noPendingDrafts') }}
      </p>
      <p v-else-if="draftsStatus === 'error'" class="brief__hint" role="status">
        {{ t('home.brief.draftsUnavailable') }}
      </p>

      <button
        v-if="brief"
        type="button"
        class="btn"
        data-test="regenerate"
        :disabled="!canRegenerate"
        @click="regenerate"
      >
        {{ regenerating ? t('home.brief.regenerating') : t('home.brief.regenerate') }}
      </button>
      <p v-if="regenerateErrorMessage" class="brief__hint" role="alert">
        {{ regenerateErrorMessage }}
      </p>
    </div>
  </section>
</template>

<style scoped>
/* 今日简报：浅色信笺——奶油到金色的淡渐变、金色左边线（原型 .brief）。 */
.brief {
  position: relative;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 22px;
  align-items: start;
  padding: 18px 22px 18px 24px;
  margin-bottom: 16px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--gilt);
  border-radius: var(--radius);
  background: linear-gradient(110deg, var(--gilt-soft) 0%, var(--card) 62%);
  box-shadow: var(--shadow-sm);
}

.brief__body {
  min-width: 0;
}

.brief__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
  margin-bottom: 8px;
}

.brief__title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--gilt-ink);
}

.brief__title::after {
  content: '';
  width: 42px;
  height: 1px;
  background: var(--gilt);
}

.brief__meta,
.brief__source,
.brief__collapsed {
  margin: 0;
  font-size: 12px;
  color: var(--ink-soft);
}

.brief__source {
  margin-top: 8px;
}

.brief__items {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.brief__item {
  min-width: 0;
}

.brief__item-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.5;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.brief__item-evidence {
  margin: 2px 0 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--ink-2);
  overflow-wrap: anywhere;
}

.brief__ask,
.brief__link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  padding: 0;
  border: 0;
  background: none;
  font-size: 12.5px;
  font-weight: 600;
  text-align: left;
  color: var(--accent-ink);
  overflow-wrap: anywhere;
}

.brief__ask:hover,
.brief__link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.brief__status {
  margin: 0;
  font-size: 14px;
  color: var(--ink-2);
}

.brief__degraded {
  margin: 0 0 10px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 13px;
  font-weight: 600;
}

.brief__actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  min-width: 0;
}

.brief__hint {
  max-width: 22ch;
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-soft);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  min-height: 34px;
  padding: 0 13px;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  background: var(--card);
  color: var(--ink);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
  transition:
    background-color 150ms,
    border-color 150ms;
}

.btn:hover {
  background: var(--hover);
  border-color: var(--ink-faint);
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn--primary {
  border-color: transparent;
  background: var(--accent);
  color: var(--on-accent);
}

.btn--primary:hover {
  border-color: transparent;
  background: var(--accent-strong);
}

@media (max-width: 820px) {
  .brief {
    grid-template-columns: minmax(0, 1fr);
    gap: 14px;
    padding: 16px 16px 16px 18px;
  }

  .brief__actions {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
  }

  .brief__hint {
    max-width: none;
  }
}
</style>
