<script setup lang="ts">
import { AlertTriangle, ExternalLink, Ruler } from '@lucide/vue'
import { computed } from 'vue'

import type { ChatAnswer } from '@/types/chat'

const props = defineProps<{ answer?: ChatAnswer }>()

const metric = computed(() => props.answer?.metric)
const queryPlan = computed(() => props.answer?.data?.queryPlan)
const isUnverified = computed(
  () => metric.value?.status === 'UNVERIFIED' || metric.value?.generated === true,
)

const sourceLabel = computed(() => {
  switch (metric.value?.source) {
    case 'METRIC_CATALOG':
      return '正式指标目录'
    case 'FIELD_COMMENT':
      return '受控字段注释'
    case 'AI_GENERATED':
      return '模型候选口径'
    default:
      return undefined
  }
})

const statusLabel = computed(() => {
  switch (metric.value?.status) {
    case 'ACTIVE':
      return '已核验'
    case 'DEPRECATED':
      return '已弃用'
    case 'UNVERIFIED':
      return '待核验'
    default:
      return undefined
  }
})
</script>

<template>
  <section class="metric-panel" aria-label="指标口径">
    <header class="metric-panel__header">
      <Ruler :size="15" aria-hidden="true" />
      <h2>指标口径</h2>
    </header>

    <div v-if="metric" class="metric-panel__body">
      <p class="metric-panel__name">{{ metric.displayName }}</p>

      <p
        v-if="isUnverified"
        class="metric-panel__alert"
        data-testid="metric-unverified"
        role="status"
      >
        <AlertTriangle :size="13" aria-hidden="true" />
        <span>{{ metric.notice ?? '该指标口径尚未核验，请谨慎参考。' }}</span>
      </p>

      <dl class="metric-panel__fields">
        <div class="metric-panel__field">
          <dt>业务口径</dt>
          <dd>{{ metric.definition }}</dd>
        </div>
        <div class="metric-panel__field">
          <dt>SQL 口径</dt>
          <dd>{{ metric.sqlDefinition }}</dd>
        </div>
        <div class="metric-panel__field">
          <dt>单位</dt>
          <dd>{{ metric.unit }}</dd>
        </div>
        <div class="metric-panel__field">
          <dt>来源</dt>
          <dd>{{ sourceLabel }}</dd>
        </div>
        <div class="metric-panel__field">
          <dt>来源库表</dt>
          <dd>{{ metric.sourceDatabase }} · {{ metric.sourceTable }}</dd>
        </div>
        <div v-if="metric.dimensions.length" class="metric-panel__field">
          <dt>可用维度</dt>
          <dd>{{ metric.dimensions.join('、') }}</dd>
        </div>
        <div v-if="metric.reportUrl" class="metric-panel__field">
          <dt>关联报表</dt>
          <dd>
            <a
              :href="metric.reportUrl"
              class="metric-panel__report-link"
              data-testid="metric-report-link"
              target="_blank"
              rel="noopener noreferrer"
            >
              打开关联报表 <ExternalLink :size="13" aria-hidden="true" />
            </a>
          </dd>
        </div>
        <div class="metric-panel__field">
          <dt>负责人</dt>
          <dd>{{ metric.owner }}</dd>
        </div>
        <div class="metric-panel__field">
          <dt>状态</dt>
          <dd>{{ statusLabel }}</dd>
        </div>
      </dl>

      <div v-if="queryPlan" class="metric-panel__query-plan" data-testid="query-plan-summary">
        <span>查询计划摘要</span>
        <p>{{ queryPlan }}</p>
      </div>
    </div>

    <div v-else class="metric-panel__empty" data-testid="metric-empty">
      <span>暂无指标口径</span>
      <p>发起指标类问题后，这里会显示对应的指标定义、来源与负责人。</p>
    </div>
  </section>
</template>

<style scoped>
.metric-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
}

.metric-panel__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
}

.metric-panel__header h2 {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-section-title);
  font-weight: var(--font-weight-emphasis);
}

.metric-panel__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2-5);
}

.metric-panel__name {
  margin: 0;
  color: var(--color-text);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
}

.metric-panel__alert {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  margin: 0;
  padding: var(--space-2) var(--space-2-5);
  border-radius: var(--radius-small);
  color: var(--color-danger-text);
  background: var(--color-danger-surface);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}

.metric-panel__fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
}

.metric-panel__field dt {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}

.metric-panel__field dd {
  margin: var(--space-0-5) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

.metric-panel__report-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--color-primary-strong);
  font-weight: var(--font-weight-emphasis);
  text-decoration: none;
}

.metric-panel__report-link:hover {
  text-decoration: underline;
}

.metric-panel__query-plan {
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}

.metric-panel__query-plan span {
  font-weight: var(--font-weight-emphasis);
}
.metric-panel__query-plan p {
  margin: var(--space-1) 0 0;
}

.metric-panel__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-2);
  color: var(--color-text-secondary);
  text-align: center;
}

.metric-panel__empty span {
  color: var(--color-text-secondary);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-emphasis);
}

.metric-panel__empty p {
  max-width: 210px;
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
}
</style>
