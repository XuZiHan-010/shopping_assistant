<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { resolveApiBaseUrl } from '@/api/client'
import { columnLabel } from '@/constants/columnLabels'
import { useLocaleStore } from '@/stores/locale'
import type { DataResult, ExportInfo } from '@/types/chat'
import { buildExportHref, exportExpiry } from '@/utils/download'
import { formatCell } from '@/utils/format'

const { t } = useI18n()
const localeStore = useLocaleStore()

const props = defineProps<{
  data: DataResult
  exportInfo?: ExportInfo
  apiBaseUrl?: string
  now?: Date
}>()

const columns = computed(() => [...new Set(props.data.rows.flatMap((row) => Object.keys(row)))])
const expiry = computed(() =>
  props.exportInfo ? exportExpiry(props.exportInfo.expiresAt, props.now) : undefined,
)
const exportHref = computed(() => {
  if (!props.exportInfo || expiry.value?.expired) return undefined

  // resolveApiBaseUrl() 在 VITE_API_BASE_URL 缺失/非法时会抛 ApiConfigError；
  // 这属于全局配置问题，其他请求路径都会走 AppError/errorCopy 正常展示，
  // 这里只是顺带拼一个下载链接，不该让整条消息的渲染直接崩掉——退化成
  // "没有下载链接"就够了。
  try {
    const apiBaseUrl = props.apiBaseUrl ?? resolveApiBaseUrl()
    return buildExportHref(apiBaseUrl, props.exportInfo.url)
  } catch {
    return undefined
  }
})
</script>

<template>
  <section
    class="detail-table"
    data-testid="detail-table"
    :aria-label="t('detailTable.sectionAria')"
  >
    <div class="detail-table__head">
      <p v-if="data.truncated" class="detail-table__notice">
        {{ t('detailTable.truncatedNotice', { total: data.totalRows, shown: data.rows.length }) }}
      </p>
      <p v-else class="detail-table__notice">
        {{ t('detailTable.fullNotice', { total: data.totalRows }) }}
      </p>
      <a
        v-if="exportHref"
        :href="exportHref"
        download
        target="_blank"
        rel="noopener"
        data-testid="download-export"
        >{{ t('detailTable.downloadLink', { minutes: expiry?.minutesRemaining }) }}</a
      >
      <p v-else-if="exportInfo" class="detail-table__expired">
        {{ t('detailTable.expiredNotice') }}
      </p>
    </div>
    <div class="detail-table__scroll">
      <table>
        <caption>
          {{
            t('detailTable.caption')
          }}
        </caption>
        <thead>
          <tr>
            <th v-for="column in columns" :key="column" scope="col">
              {{ columnLabel(column, localeStore.locale) }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in data.rows" :key="index">
            <td v-for="column in columns" :key="column">
              {{ formatCell(row[column], localeStore.locale) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.detail-table {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
.detail-table__head {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}
.detail-table__notice,
.detail-table__expired {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
}
.detail-table__expired {
  color: var(--color-danger-text);
}
.detail-table__head a {
  color: var(--color-primary-strong);
  font-size: var(--font-size-caption);
}
.detail-table__scroll {
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-small);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption);
  white-space: nowrap;
}
caption {
  padding: var(--space-2);
  text-align: left;
  font-weight: var(--font-weight-emphasis);
}
th,
td {
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
  text-align: left;
}
th {
  position: sticky;
  top: 0;
  background: var(--color-surface-muted);
}
</style>
