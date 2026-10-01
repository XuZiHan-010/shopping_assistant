<script setup lang="ts">
/**
 * 带色点的状态胶囊（W Task 9 起：订单、商品页；Task 10 起各工作区页面共用）。
 * 颜色只取 token，文案由调用方经 i18n 传入。
 */
import type { PillTone } from './pillTone'

defineProps<{ tone: PillTone }>()
</script>

<template>
  <span class="pill" :class="`pill--${tone}`"><slot /></span>
</template>

<style scoped>
.pill {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 5px;
  padding: 1px 8px;
  border-radius: 99px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.6;
  white-space: nowrap;
}

.pill::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.pill--ok {
  background: var(--ok-soft);
  color: var(--ok);
}

.pill--warn {
  background: var(--warn-soft);
  color: var(--warn);
}

.pill--danger {
  background: var(--danger-soft);
  color: var(--danger);
}

.pill--info {
  background: var(--info-soft);
  color: var(--info);
}

.pill--violet {
  background: var(--violet-soft);
  color: var(--violet);
}

.pill--muted {
  background: var(--well);
  color: var(--ink-soft);
}
</style>
