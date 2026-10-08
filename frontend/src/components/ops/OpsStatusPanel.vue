<script setup lang="ts">
/**
 * 运维看板的内容区（N5 B Task 3 步骤 3；PRD §10.4、§14，D-N5-1）。
 *
 * 一页合并 `/api/admin/ops/status`（三级预算、成本、限流、降级、工具错误率、p95）与 Chat BI 概览。
 * 只读：除「刷新」外没有任何按钮，不提供 Chat BI 手动回补等写操作。
 * 本组件一挂载就加载数据，所以**只能渲染在 `AdminGate` 的插槽里**（见 `OpsStatusView`）：
 * 令牌验证通过前它不存在，也就不会发任何 `/api/admin/*` 请求。
 * 只读令牌（VIEWER_TOKEN）读得到 Chat BI，读不到 ops/status（R6），此时如实提示而不是报错整页。
 * 不渲染任何 Token、Prompt、经营数据或请求正文；店铺级预算只显示后端给的脱敏标识。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { fetchChatBiOverview, fetchOpsStatus } from '@/api/adapters/adminOps'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import type { ChatBiOverview, OpsStatus } from '@/types/opsStatus'

const { t, n, te } = useI18n()
const status = ref<OpsStatus | null>(null)
const overview = ref<ChatBiOverview | null>(null)
const opsForbidden = ref(false)
const loadFailed = ref(false)
const loading = ref(false)
let controller: AbortController | null = null

function isForbidden(error: unknown): boolean {
  const code = typeof error === 'object' && error !== null && 'status' in error
    ? (error as { status?: number }).status
    : undefined
  return code === 403
}

async function load(): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  const { signal } = controller
  loading.value = true
  loadFailed.value = false
  opsForbidden.value = false
  const [ops, chatbi] = await Promise.allSettled([fetchOpsStatus(signal), fetchChatBiOverview(signal)])
  if (signal.aborted) return
  if (ops.status === 'fulfilled') {
    status.value = ops.value
  } else {
    status.value = null
    if (isForbidden(ops.reason)) opsForbidden.value = true
    else loadFailed.value = true
  }
  if (chatbi.status === 'fulfilled') overview.value = chatbi.value
  else loadFailed.value = true
  loading.value = false
}

function percent(value: number | null): string {
  return value === null ? t('opsStatus.none') : n(value, { style: 'percent', maximumFractionDigits: 1 })
}

/** 原因码有文案就用文案，没有就原样显示码——后端新增原因时不会显示成空白。 */
function reasonLabel(code: string): string {
  const key = `opsStatus.degradedReason.${code}`
  return te(key) ? t(key) : code
}

function tokens(value: number): string {
  return n(value)
}

onMounted(() => void load())
onUnmounted(() => controller?.abort())
</script>

<template>
  <WorkspacePage title-id="ops-status-title" :title="t('opsStatus.title')">
    <template #intro>
      <p class="ops__eyebrow">{{ t('opsStatus.eyebrow') }}</p>
      <p class="ops__sub">{{ t('opsStatus.sub') }}</p>
    </template>
    <template #actions>
      <button type="button" :disabled="loading" @click="load">{{ t('opsStatus.refresh') }}</button>
    </template>

    <p v-if="loading && !status && !overview" role="status">{{ t('opsStatus.loading') }}</p>
    <p v-if="loadFailed" role="alert" data-testid="ops-error">{{ t('opsStatus.loadFailed') }}</p>
    <p v-if="opsForbidden" role="status" data-testid="ops-forbidden">{{ t('opsStatus.forbidden') }}</p>

    <template v-if="status">
      <section class="ops__card" data-testid="ops-budget" aria-labelledby="ops-budget-title">
        <h2 id="ops-budget-title">{{ t('opsStatus.budgetTitle') }}</h2>
        <p class="ops__hint">{{ t('opsStatus.budgetHint') }}</p>
        <div class="ops__scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{{ t('opsStatus.columns.level') }}</th>
                <th scope="col">{{ t('opsStatus.columns.scope') }}</th>
                <th scope="col">{{ t('opsStatus.columns.budget') }}</th>
                <th scope="col">{{ t('opsStatus.columns.used') }}</th>
                <th scope="col">{{ t('opsStatus.columns.remaining') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in status.budgetLevels" :key="row.scope" :class="{ 'ops__exhausted': row.remainingTokens === 0 }">
                <td>{{ t(`opsStatus.level.${row.level}`) }}</td>
                <td><code>{{ row.scope }}</code></td>
                <td>{{ tokens(row.budgetTokens) }}</td>
                <td>{{ tokens(row.usedTokens) }}</td>
                <td>{{ tokens(row.remainingTokens) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="ops__card" data-testid="ops-cost" aria-labelledby="ops-cost-title">
        <h2 id="ops-cost-title">{{ t('opsStatus.costTitle') }}</h2>
        <dl class="ops__stats">
          <div>
            <dt>{{ t('opsStatus.cost') }}</dt>
            <dd v-if="status.costToday.length">
              <span v-for="row in status.costToday" :key="row.currency">{{ row.amount }} {{ row.currency }}</span>
            </dd>
            <dd v-else>{{ t('opsStatus.noCost') }}</dd>
          </div>
          <div>
            <dt>{{ t('opsStatus.cacheRate') }}</dt>
            <dd>{{ percent(status.cacheHitRateToday) }}</dd>
          </div>
          <div>
            <dt>{{ t('opsStatus.cacheTokens') }}</dt>
            <dd>{{ tokens(status.cacheHitTokensToday) }}</dd>
          </div>
        </dl>
        <p v-if="status.unpricedCallsToday > 0" class="ops__hint" data-testid="ops-unpriced">
          {{ t('opsStatus.unpriced', { count: status.unpricedCallsToday }) }}
        </p>
      </section>

      <section class="ops__card" data-testid="ops-turns" aria-labelledby="ops-turns-title">
        <h2 id="ops-turns-title">{{ t('opsStatus.turnsTitle') }}</h2>
        <p class="ops__hint">{{ t('opsStatus.turnsHint') }}</p>
        <dl class="ops__stats">
          <div><dt>{{ t('opsStatus.turns') }}</dt><dd>{{ tokens(status.turnsToday) }}</dd></div>
          <div>
            <dt>{{ t('opsStatus.avgTokens') }}</dt>
            <dd>{{ status.avgTokensPerTurnToday === null ? t('opsStatus.none') : n(status.avgTokensPerTurnToday, { maximumFractionDigits: 0 }) }}</dd>
          </div>
          <div>
            <dt>{{ t('opsStatus.avgCost') }}</dt>
            <dd v-if="status.avgCostPerTurnToday.length">
              <span v-for="row in status.avgCostPerTurnToday" :key="row.currency">{{ row.amount }} {{ row.currency }}</span>
            </dd>
            <dd v-else>{{ t('opsStatus.none') }}</dd>
          </div>
          <div>
            <dt>{{ t('opsStatus.avgElapsed') }}</dt>
            <dd>{{ status.avgTurnElapsedMsToday === null ? t('opsStatus.none') : `${n(status.avgTurnElapsedMsToday, { maximumFractionDigits: 0 })} ms` }}</dd>
          </div>
        </dl>
      </section>

      <section class="ops__card" data-testid="ops-runtime" aria-labelledby="ops-runtime-title">
        <h2 id="ops-runtime-title">{{ t('opsStatus.runtimeTitle') }}</h2>
        <dl class="ops__stats">
          <div><dt>{{ t('opsStatus.rateLimitHits') }}</dt><dd>{{ status.rateLimitHits }}</dd></div>
          <div><dt>{{ t('opsStatus.degraded') }}</dt><dd>{{ status.degradedCount }}</dd></div>
          <div><dt>{{ t('opsStatus.toolCalls') }}</dt><dd>{{ status.toolCallsTotal }}</dd></div>
          <div><dt>{{ t('opsStatus.toolErrorRate') }}</dt><dd>{{ percent(status.toolErrorRate) }}</dd></div>
          <div>
            <dt>{{ t('opsStatus.demoMode') }}</dt>
            <dd>{{ status.demoDeploymentMode ? t('opsStatus.on') : t('opsStatus.off') }}</dd>
          </div>
        </dl>
        <template v-if="status.degradedReasons.length">
          <h3>{{ t('opsStatus.degradedReasonsTitle') }}</h3>
          <ul class="ops__list" data-testid="ops-degraded-reasons">
            <li v-for="row in status.degradedReasons" :key="row.reason">
              <span>{{ reasonLabel(row.reason) }}</span><strong>{{ row.count }}</strong>
            </li>
          </ul>
        </template>
        <template v-if="status.sourceDegradations.length">
          <h3>{{ t('opsStatus.sourceDegradationsTitle') }}</h3>
          <ul class="ops__list" data-testid="ops-source-degradations">
            <li v-for="row in status.sourceDegradations" :key="row.source">
              <code>{{ row.source }}</code><strong>{{ row.count }}</strong>
            </li>
          </ul>
        </template>
      </section>

      <section class="ops__card" data-testid="ops-routes" aria-labelledby="ops-routes-title">
        <h2 id="ops-routes-title">{{ t('opsStatus.routesTitle') }}</h2>
        <p v-if="!status.routeP95.length" class="ops__hint">{{ t('opsStatus.none') }}</p>
        <div v-else class="ops__scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{{ t('opsStatus.columns.route') }}</th>
                <th scope="col">{{ t('opsStatus.columns.p95') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in status.routeP95" :key="row.route">
                <td><code>{{ row.route }}</code></td>
                <td>{{ n(row.p95Ms, { maximumFractionDigits: 0 }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <section v-if="overview" class="ops__card" data-testid="chatbi-overview" aria-labelledby="chatbi-title">
      <h2 id="chatbi-title">{{ t('opsStatus.chatbiTitle') }}</h2>
      <p class="ops__hint">{{ t('opsStatus.chatbiRange', { start: overview.startDate, end: overview.endDate }) }}</p>
      <dl class="ops__stats">
        <div><dt>{{ t('opsStatus.answers') }}</dt><dd>{{ overview.answerTotal }}</dd></div>
        <div><dt>{{ t('opsStatus.adoption') }}</dt><dd>{{ percent(overview.adoptionRate) }}</dd></div>
        <div><dt>{{ t('opsStatus.systemAccuracy') }}</dt><dd>{{ percent(overview.systemAccuracyRate) }}</dd></div>
        <div><dt>{{ t('opsStatus.hitRate') }}</dt><dd>{{ percent(overview.hitRate) }}</dd></div>
        <div><dt>{{ t('opsStatus.failureRate') }}</dt><dd>{{ percent(overview.failureRate) }}</dd></div>
        <div>
          <dt>{{ t('opsStatus.avgThinking') }}</dt>
          <dd>{{ overview.avgThinkingMs === null ? t('opsStatus.none') : `${n(overview.avgThinkingMs, { maximumFractionDigits: 0 })} ms` }}</dd>
        </div>
      </dl>
      <h3>{{ t('opsStatus.dailyTitle') }}</h3>
      <div class="ops__scroll" data-testid="chatbi-daily">
        <table>
          <thead>
            <tr>
              <th scope="col">{{ t('opsStatus.columns.date') }}</th>
              <th scope="col">{{ t('opsStatus.columns.answers') }}</th>
              <th scope="col">{{ t('opsStatus.columns.accuracy') }}</th>
              <th scope="col">{{ t('opsStatus.columns.hitRate') }}</th>
              <th scope="col">{{ t('opsStatus.columns.failureRate') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="day in overview.daily" :key="day.statDate">
              <td>{{ day.statDate }}</td>
              <td>{{ day.answerTotal }}</td>
              <td>{{ percent(day.systemAccuracyRate) }}</td>
              <td>{{ percent(day.hitRate) }}</td>
              <td>{{ percent(day.failureRate) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </WorkspacePage>
</template>

<style scoped>
.ops__eyebrow {
  margin: 0;
  color: var(--ink-soft);
  font-size: var(--font-size-caption);
}
.ops__sub,
.ops__hint {
  margin: 0.25rem 0 0;
  color: var(--ink-soft);
}
.ops__card {
  margin-top: 1rem;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  background: var(--card);
}
.ops__card h2 {
  margin: 0;
  font-size: var(--font-size-section-title);
}
.ops__card h3 {
  margin: 1rem 0 0.5rem;
  font-size: 0.9rem;
}
.ops__stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: 0.75rem;
  margin: 0.75rem 0 0;
}
.ops__stats dt {
  color: var(--ink-soft);
  font-size: var(--font-size-caption);
}
.ops__stats dd {
  margin: 0.15rem 0 0;
  font-variant-numeric: tabular-nums;
  font-weight: var(--font-weight-emphasis);
}
.ops__list {
  display: grid;
  gap: 0.35rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.ops__list li {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-variant-numeric: tabular-nums;
}
.ops__scroll {
  overflow-x: auto;
  margin-top: 0.75rem;
}
.ops__scroll table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}
.ops__scroll th,
.ops__scroll td {
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid var(--line);
  text-align: left;
  white-space: nowrap;
}
.ops__exhausted td {
  color: var(--danger);
}
</style>
