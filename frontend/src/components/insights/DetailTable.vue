<script setup lang="ts">
import { computed } from 'vue'

import { resolveApiBaseUrl } from '@/api/client'
import { columnLabel } from '@/constants/columnLabels'
import type { DataResult, ExportInfo } from '@/types/chat'
import { buildExportHref, exportExpiry } from '@/utils/download'
import { formatCell } from '@/utils/format'

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
  <section class="detail-table" data-testid="detail-table" aria-label="经营明细">
    <div class="detail-table__head">
      <p v-if="data.truncated" class="detail-table__notice">
        共 {{ data.totalRows }} 行，已展示前 {{ data.rows.length }} 行，完整数据请下载 CSV。
      </p>
      <p v-else class="detail-table__notice">共 {{ data.totalRows }} 行。</p>
      <a
        v-if="exportHref"
        :href="exportHref"
        download
        target="_blank"
        rel="noopener"
        data-testid="download-export"
        >下载明细 CSV（链接 {{ expiry?.minutesRemaining }} 分钟后过期）</a
      >
      <p v-else-if="exportInfo" class="detail-table__expired">
        下载链接已过期，重新提问可生成新的导出。
      </p>
    </div>
    <div class="detail-table__scroll">
      <table>
        <caption>
          经营明细
        </caption>
        <thead>
          <tr>
            <th v-for="column in columns" :key="column" scope="col">{{ columnLabel(column) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in data.rows" :key="index">
            <td v-for="column in columns" :key="column">{{ formatCell(row[column]) }}</td>
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
