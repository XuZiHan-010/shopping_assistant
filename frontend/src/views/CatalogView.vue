<script setup lang="ts">
/**
 * 商品页（W Task 9，契约 §8.12.3 `GET /api/v2/merchant/products/content`）。
 *
 * - 内容完整度与缺口标签逐字来自后端：`content_complete`、`missing_required_attributes`、
 *   `missing_content_fields` 由后端按类目规则确定性计算，页面**不**自行判定缺口（R4/R7）；
 *   界面只把两个已知的内容字段名（商品描述、商品图片）翻成当前语言，类目属性名保持后端原文；
 * - 本端点没有降级字段：数据源不可用时是 503 错误，页面显示“暂时无法读取”并可重试，
 *   不回退到任何示意数据；
 * - 「检查内容缺口」「起草补充」只经 `rail.ask()` 预填助手，不发送、不写任何数据；
 * - 取数直接用 Adapter，分页状态机与订单页共用 `useCursorList`（令牌、INVALID_CURSOR 从第一页
 *   重读并提示）；不共用库存页的 `catalogOps` Store：那份 Store 同时拉优惠券、没有请求令牌，
 *   两页共用会互相覆盖游标。
 */
import { Sparkles } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  fetchMerchantProductContent,
  type MerchantProductContent,
} from '@/api/adapters/merchantOps'
import {
  CONTENT_FIELD_KEYS,
  isKnownProductStatus,
  productStatusTone,
} from '@/components/catalog/productContent'
import type { PillTone } from '@/components/layout/pillTone'
import StatusPill from '@/components/layout/StatusPill.vue'
import WorkspacePage from '@/components/layout/WorkspacePage.vue'
import { focusIfLost, useCursorList } from '@/composables/useCursorList'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'
import { useRailStore } from '@/stores/rail'
import { formatNumber } from '@/utils/localizedFormat'

const PAGE_SIZE = 20

const { t } = useI18n()
const auth = useAuthStore()
const rail = useRailStore()
const localeStore = useLocaleStore()
const locale = computed(() => localeStore.locale)

const {
  items: products,
  status,
  moreStatus,
  hasMore,
  restarted,
  reload,
  loadMore,
} = useCursorList<MerchantProductContent>((cursor) =>
  auth.callWithSessionRetry((sid) =>
    fetchMerchantProductContent(sid, { cursor, limit: PAGE_SIZE }),
  ),
)

watch(locale, () => void reload(), { immediate: true })

// ---------- 焦点 ----------
const panel = ref<HTMLElement | null>(null)

/** 重试按钮会随错误态消失：先把焦点交给列表面板，再重读。 */
function retry(): void {
  panel.value?.focus()
  void reload()
}

// INVALID_CURSOR 恢复会清掉列表与「加载更多」按钮；焦点若因此掉到 body，交给列表面板。
watch(
  restarted,
  (value) => {
    if (value) focusIfLost(panel.value)
  },
  { flush: 'post' },
)

function contentFieldLabel(field: string): string {
  const key = CONTENT_FIELD_KEYS[field]
  return key ? t(`catalogPage.contentField.${key}`) : field
}

/** 缺口名称按后端顺序：先类目必填属性，再内容字段。 */
function gapNames(product: MerchantProductContent): string[] {
  return [
    ...product.missingRequiredAttributes,
    ...product.missingContentFields.map(contentFieldLabel),
  ]
}

function statusLabel(value: string): string {
  return isKnownProductStatus(value) ? t(`catalogPage.status.${value}`) : value
}

function statusTone(value: string): PillTone {
  return productStatusTone(value)
}

function askGaps(): void {
  rail.ask(t('catalogPage.askPrompt'))
}

function askDraft(product: MerchantProductContent): void {
  rail.ask(
    t('catalogPage.draftFillPrompt', {
      name: product.title,
      gaps: gapNames(product).join(t('catalogPage.gapSeparator')),
    }),
  )
}
</script>

<template>
  <WorkspacePage title-id="page-title-catalog" :title="t('pages.catalog.title')">
    <template #intro>
      <p>{{ t('catalogPage.sub') }}</p>
    </template>
    <template #actions>
      <button type="button" class="ask" data-test="catalog-ask" @click="askGaps">
        <Sparkles :size="13" aria-hidden="true" />
        <span>{{ t('catalogPage.ask') }}</span>
      </button>
    </template>

    <div
      ref="panel"
      class="ws-panel"
      role="region"
      tabindex="-1"
      data-test="catalog-panel"
      :aria-label="t('catalogPage.caption')"
    >
      <div class="live" role="status">
        <p v-if="restarted" class="ws-notice" data-test="catalog-restarted">
          {{ t('catalogPage.restarted') }}
        </p>
      </div>
      <p v-if="status === 'loading'" class="ws-state" role="status">
        {{ t('catalogPage.loading') }}
      </p>
      <div v-else-if="status === 'error'" class="ws-state" role="alert">
        <span>{{ t('catalogPage.loadFailed') }}</span>
        <button type="button" class="ws-link" data-test="catalog-retry" @click="retry">
          {{ t('catalogPage.retry') }}
        </button>
      </div>
      <p v-else-if="products.length === 0" class="ws-state" data-test="catalog-empty">
        {{ t('catalogPage.empty') }}
      </p>

      <template v-else>
        <table class="ws-table">
          <caption class="sr-only">
            {{
              t('catalogPage.caption')
            }}
          </caption>
          <thead>
            <tr>
              <th scope="col">{{ t('catalogPage.columns.product') }}</th>
              <th scope="col">{{ t('catalogPage.columns.category') }}</th>
              <th scope="col" class="r">{{ t('catalogPage.columns.available') }}</th>
              <th scope="col">{{ t('catalogPage.columns.content') }}</th>
              <th scope="col">{{ t('catalogPage.columns.status') }}</th>
              <th scope="col">
                <span class="sr-only">{{ t('catalogPage.columns.actions') }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="product in products" :key="product.id" data-test="product-row">
              <td class="cell-product">
                <strong class="name">{{ product.title }}</strong>
                <span class="ws-sub ws-mono" translate="no">{{ product.id }}</span>
              </td>
              <td class="cell-category">{{ product.category }}</td>
              <td class="cell-stock r">
                <strong>{{ formatNumber(product.stockAvailable, locale) }}</strong>
                <span class="ws-sub">
                  {{
                    t('catalogPage.stockDetail', {
                      onHand: formatNumber(product.stockOnHand, locale),
                      reserved: formatNumber(product.stockReserved, locale),
                    })
                  }}
                </span>
              </td>
              <td class="cell-content">
                <StatusPill v-if="product.contentComplete" tone="ok" data-test="content-complete">
                  {{ t('catalogPage.complete') }}
                </StatusPill>
                <template v-else>
                  <StatusPill tone="warn" data-test="content-incomplete">
                    {{ t('catalogPage.incomplete') }}
                  </StatusPill>
                </template>
                <ul v-if="gapNames(product).length > 0" class="gaps">
                  <li
                    v-for="attribute in product.missingRequiredAttributes"
                    :key="`attr-${attribute}`"
                    class="gap"
                    data-test="gap-tag"
                  >
                    {{ t('catalogPage.missing', { name: attribute }) }}
                  </li>
                  <li
                    v-for="field in product.missingContentFields"
                    :key="`field-${field}`"
                    class="gap"
                    data-test="gap-tag"
                  >
                    {{ t('catalogPage.missing', { name: contentFieldLabel(field) }) }}
                  </li>
                </ul>
              </td>
              <td class="cell-status">
                <StatusPill :tone="statusTone(product.status)">
                  {{ statusLabel(product.status) }}
                </StatusPill>
              </td>
              <td class="cell-actions r">
                <button
                  v-if="!product.contentComplete"
                  type="button"
                  class="ask"
                  data-test="product-ask"
                  :aria-label="t('catalogPage.draftFillAria', { name: product.title })"
                  @click="askDraft(product)"
                >
                  <Sparkles :size="13" aria-hidden="true" />
                  <span>{{ t('catalogPage.draftFill') }}</span>
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="hasMore || moreStatus === 'error'" class="ws-more">
          <span v-if="moreStatus === 'error'" class="ws-more__error" role="alert">
            {{ t('catalogPage.loadMoreFailed') }}
          </span>
          <button
            v-if="hasMore"
            type="button"
            class="ws-btn ws-btn--sm"
            data-test="catalog-load-more"
            :disabled="moreStatus === 'loading'"
            @click="loadMore"
          >
            {{
              moreStatus === 'loading' ? t('catalogPage.loadingMore') : t('catalogPage.loadMore')
            }}
          </button>
        </div>
      </template>
    </div>
  </WorkspacePage>
</template>

<style scoped>
/* 面板、状态行、表格、「加载更多」与 820px 卡片化的共用规则在 assets/workspace.css（ws-*）。 */
.ask {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 11px;
  border: 0;
  border-radius: 99px;
  background: var(--accent-soft);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--accent-ink);
  white-space: nowrap;
}

.ask:hover {
  background: var(--accent);
  color: var(--on-accent);
}

.name {
  display: block;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.cell-stock .ws-sub {
  white-space: nowrap;
}

.gaps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.gap {
  padding: 1px 7px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  font-size: 12px;
  color: var(--ink-2);
  overflow-wrap: anywhere;
}

/* 820px 以下：每件两列排布（商品 | 库存；类目；内容占满一行；状态 | 操作）。 */
@media (max-width: 820px) {
  .cell-product {
    grid-column: 1;
  }

  .cell-stock {
    grid-column: 2;
    grid-row: 1;
  }

  .cell-category {
    grid-column: 1;
    font-size: 12px;
    color: var(--ink-soft);
  }

  .cell-content {
    grid-column: 1 / -1;
  }

  .cell-status {
    grid-column: 1;
  }

  .cell-actions {
    grid-column: 2;
    text-align: right;
  }
}
</style>
