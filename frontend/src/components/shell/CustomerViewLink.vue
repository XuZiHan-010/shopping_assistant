<script setup lang="ts">
/**
 * 「顾客视角」入口（PRD M1、§10.7，D-N5-4）：在新标签页打开本店的顾客端店铺页。
 *
 * **只是一个链接**：地址 = 构建变量 `VITE_SHOP_BASE_URL` + 后端从已验证会话给出的 `shop_slug`。
 * 不带会话 ID、演示 Token 或任何查询参数；顾客端照常创建自己的访客会话（R5）。
 * `noopener noreferrer` 让新标签拿不到本页的 `window.opener`，也不带来源地址。
 * 变量缺失或没有会话时不渲染，不回退到同源或硬编码地址。
 */
import { ArrowUpRight, Store } from '@lucide/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { resolveShopBaseUrl } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const auth = useAuthStore()

const href = computed(() => {
  const base = resolveShopBaseUrl()
  if (!base || !auth.sessionId || !auth.shopSlug) return null
  return `${base}/${encodeURIComponent(auth.shopSlug)}`
})
</script>

<template>
  <a
    v-if="href"
    class="customer-view"
    data-testid="customer-view-link"
    :href="href"
    target="_blank"
    rel="noopener noreferrer"
    :title="t('shell.customerViewHint')"
  >
    <Store :size="18" aria-hidden="true" />
    <span>{{ t('shell.customerView') }}</span>
    <ArrowUpRight :size="16" aria-hidden="true" class="customer-view__out" />
  </a>
</template>

<style scoped>
/* 侧栏里唯一的实心按钮：品牌金底 + 铸铁绿字（与账号头像同一组配色），在深绿侧栏上一眼可见。 */
.customer-view {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  min-height: 42px;
  padding: 9px 12px;
  border-radius: 11px;
  background: var(--gilt);
  color: var(--iron);
  font-size: 14px;
  font-weight: 700;
  text-decoration: none;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.22);
  transition:
    filter 150ms,
    transform 150ms;
}

.customer-view:hover {
  filter: brightness(1.08);
}

.customer-view:active {
  transform: translateY(1px);
}

.customer-view:focus-visible {
  outline: 2px solid var(--side-ink);
  outline-offset: 2px;
}

.customer-view > span {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.customer-view > svg {
  flex: none;
}

/* 右侧箭头提示「会跳到新标签页」。 */
.customer-view__out {
  opacity: 0.75;
}

@media (prefers-reduced-motion: reduce) {
  .customer-view {
    transition: none;
  }
}
</style>
