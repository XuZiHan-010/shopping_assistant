<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { triggerChatBiRollup } from '@/api/analytics'
import CategoryTable from '@/components/analytics/CategoryTable.vue'
import NorthStarCards from '@/components/analytics/NorthStarCards.vue'
import LanguageSwitcher from '@/components/layout/LanguageSwitcher.vue'
import AdminTokenDialog from '@/components/knowledge/AdminTokenDialog.vue'
import { useAnalyticsStore } from '@/stores/analytics'

const TrendChart = defineAsyncComponent(() => import('@/components/analytics/TrendChart.vue'))

const { t } = useI18n()
const analyticsStore = useAnalyticsStore()
const authorizationError = ref('')
const refreshError = ref('')
const refreshing = ref(false)
const windows = [7, 30, 90] as const

const displayedError = computed(
  () => authorizationError.value || refreshError.value || analyticsStore.errorMessage,
)

async function authorize(token: string): Promise<void> {
  authorizationError.value = ''
  analyticsStore.setAdminToken(token)
  try {
    await analyticsStore.load()
  } catch (error) {
    authorizationError.value =
      error instanceof Error ? error.message : t('opsDashboardView.tokenVerificationFailed')
    analyticsStore.signOut()
  }
}

async function selectWindow(days: (typeof windows)[number]): Promise<void> {
  refreshError.value = ''
  analyticsStore.setWindowDays(days)
  try {
    await analyticsStore.load()
  } catch {
    // Store 已将可读错误写入 errorMessage；这里不重复覆盖它。
  }
}

async function refreshRollup(): Promise<void> {
  if (refreshing.value) return
  refreshing.value = true
  refreshError.value = ''
  try {
    await triggerChatBiRollup(analyticsStore.window, new AbortController().signal)
    await analyticsStore.load()
  } catch (error) {
    refreshError.value =
      error instanceof Error ? error.message : t('opsDashboardView.refreshFailed')
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  if (!analyticsStore.adminToken) return
  void analyticsStore.load().catch(() => undefined)
})
</script>

<template>
  <main class="ops-dashboard">
    <template v-if="!analyticsStore.adminToken">
      <div class="ops-dashboard__pre-auth-actions">
        <LanguageSwitcher />
      </div>
      <AdminTokenDialog
        :title="t('opsDashboardView.title')"
        :eyebrow="t('opsDashboardView.eyebrow')"
        @submit="authorize"
      />
      <p v-if="authorizationError" class="ops-dashboard__authorization-error" role="alert">
        {{ authorizationError }}
      </p>
    </template>
    <template v-else>
      <header class="ops-dashboard__header">
        <div>
          <p class="ops-dashboard__eyebrow">{{ t('opsDashboardView.eyebrow') }}</p>
          <h1>{{ t('opsDashboardView.title') }}</h1>
          <p class="ops-dashboard__caption">{{ t('opsDashboardView.caption') }}</p>
        </div>
        <div class="ops-dashboard__header-actions">
          <LanguageSwitcher />
          <button type="button" class="ops-dashboard__signout" @click="analyticsStore.signOut">
            {{ t('opsDashboardView.signOut') }}
          </button>
        </div>
      </header>

      <section class="ops-dashboard__controls" :aria-label="t('opsDashboardView.controlsAria')">
        <div
          class="ops-dashboard__windows"
          role="group"
          :aria-label="t('opsDashboardView.windowsAria')"
        >
          <button
            v-for="days in windows"
            :key="days"
            type="button"
            :aria-pressed="analyticsStore.windowDays === days"
            :class="{ 'ops-dashboard__window--active': analyticsStore.windowDays === days }"
            @click="selectWindow(days)"
          >
            {{ t('opsDashboardView.windowLabel', { days }) }}
          </button>
        </div>
        <button
          type="button"
          class="ops-dashboard__refresh"
          :disabled="refreshing"
          @click="refreshRollup"
        >
          {{ refreshing ? t('opsDashboardView.refreshing') : t('opsDashboardView.refresh') }}
        </button>
      </section>

      <p v-if="displayedError" class="ops-dashboard__error" role="alert">{{ displayedError }}</p>
      <p v-if="analyticsStore.loading" class="ops-dashboard__loading" aria-live="polite">
        {{ t('opsDashboardView.loading') }}
      </p>

      <section
        v-if="analyticsStore.overview && !analyticsStore.loading"
        class="ops-dashboard__content"
        :aria-busy="analyticsStore.loading"
      >
        <NorthStarCards :metrics="analyticsStore.overview.metrics" />
        <TrendChart
          v-if="analyticsStore.overview.daily.length > 0"
          :daily="analyticsStore.overview.daily"
        />
        <CategoryTable :rows="analyticsStore.categories" />
      </section>
    </template>
  </main>
</template>

<style scoped>
.ops-dashboard {
  min-height: 100vh;
  padding: var(--space-6);
  background: var(--color-surface-muted);
}

.ops-dashboard__header,
.ops-dashboard__controls,
.ops-dashboard__content,
.ops-dashboard__error,
.ops-dashboard__loading {
  width: min(100%, 76rem);
  margin-right: auto;
  margin-left: auto;
}

.ops-dashboard__header,
.ops-dashboard__controls {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  align-items: center;
}

.ops-dashboard__header {
  margin-bottom: var(--space-4);
}

.ops-dashboard__eyebrow,
.ops-dashboard__caption,
.ops-dashboard__header h1 {
  margin: 0;
}

.ops-dashboard__eyebrow {
  color: var(--color-teal);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-title);
  letter-spacing: 0.12em;
}

.ops-dashboard__header h1 {
  margin-top: var(--space-1);
  font-size: var(--font-size-page-title);
}

.ops-dashboard__caption {
  margin-top: var(--space-1);
  color: var(--color-text-secondary);
  font-size: var(--font-size-control);
}

.ops-dashboard__header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.ops-dashboard__signout,
.ops-dashboard__windows button,
.ops-dashboard__refresh {
  min-height: var(--control-height);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font: inherit;
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
}

.ops-dashboard__signout,
.ops-dashboard__refresh {
  padding: 0 var(--space-4);
}

.ops-dashboard__controls {
  margin-bottom: var(--space-4);
}

.ops-dashboard__windows {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.ops-dashboard__windows button {
  padding: 0 var(--space-3);
}

.ops-dashboard__windows .ops-dashboard__window--active,
.ops-dashboard__refresh {
  border-color: var(--color-primary);
  color: white;
  background: var(--color-primary);
}

.ops-dashboard__refresh:disabled {
  cursor: wait;
  opacity: 0.7;
}

.ops-dashboard__content {
  display: grid;
  gap: var(--space-4);
}

.ops-dashboard__error,
.ops-dashboard__authorization-error {
  color: var(--color-danger-text);
}

.ops-dashboard__authorization-error {
  width: min(100%, 31rem);
  margin: calc(-1 * var(--space-6)) auto 0;
}

.ops-dashboard__pre-auth-actions {
  display: flex;
  justify-content: flex-end;
  width: min(100%, 31rem);
  margin: 0 auto var(--space-4);
}

.ops-dashboard__loading {
  color: var(--color-text-secondary);
}

@media (max-width: 42rem) {
  .ops-dashboard {
    padding: var(--space-4);
  }

  .ops-dashboard__header,
  .ops-dashboard__controls {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
