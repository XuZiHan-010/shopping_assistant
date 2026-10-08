<script setup lang="ts">
/**
 * 工作区页面的页面框架（W Task 9 起：订单页、商品页；Task 10 起库存、审批、售后、
 * 顾客信号、商家记忆）：页标题、说明、右侧动作与正文。
 *
 * 只负责版式（与首页同一最大宽度与边距，820px 以下收窄），不取数、不含业务文案。
 * 同时引入共用的 `assets/workspace.css`（`ws-*` 面板、表格、按钮），见文件末尾。
 */
defineProps<{
  /** `<h1>` 的 id，同时作为整页 `aria-labelledby`。 */
  titleId: string
  title: string
}>()
</script>

<template>
  <section class="page" :aria-labelledby="titleId">
    <header class="page__head">
      <div class="page__intro">
        <h1 :id="titleId">{{ title }}</h1>
        <slot name="intro" />
      </div>
      <div v-if="$slots.actions" class="page__actions">
        <slot name="actions" />
      </div>
    </header>
    <slot />
  </section>
</template>

<style scoped>
.page {
  max-width: 1160px;
  margin: 0 auto;
  padding: 30px 36px 56px;
}

.page__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}

.page__intro {
  min-width: 0;
}

.page__head h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(26px, 2.6vw, 32px);
  font-weight: 600;
  letter-spacing: -0.015em;
  line-height: 1.15;
}

.page__intro :slotted(p) {
  max-width: 64ch;
  margin: 7px 0 0;
  font-size: 14px;
  line-height: 1.55;
  color: var(--ink-2);
  overflow-wrap: anywhere;
}

.page__actions {
  flex-shrink: 0;
}

@media (max-width: 820px) {
  .page {
    padding: 18px 16px 40px;
  }

  .page__head {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .page__head h1 {
    font-size: 22px;
  }
}
</style>

<!-- 各工作区页面共用的 ws-* 类（非 scoped）；随本组件进入懒加载页面的 chunk，不进首屏入口。 -->
<style src="../../assets/workspace.css"></style>
