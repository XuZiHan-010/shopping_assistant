<script setup lang="ts">
/**
 * Borough 商标：市集大厅的铸铁拱门 + 字母 B（金底铸铁绿线），取自定稿原型。
 * 纯装饰：旁边总有可读的品牌文字，因此对读屏隐藏。
 * `public/borough-logo.svg`（favicon 与顾客端共用）是否换成本商标另行确认，这里不动它。
 */
</script>

<template>
  <svg class="brand-mark" viewBox="0 0 40 40" aria-hidden="true" focusable="false">
    <rect width="40" height="40" rx="11" fill="#c39a3a" />
    <path d="M7 33V19a13 13 0 0 1 26 0v14" fill="none" stroke="#1f3b2f" stroke-width="2.4" />
    <path
      d="M12 33V20a8 8 0 0 1 16 0v13"
      fill="none"
      stroke="#1f3b2f"
      stroke-width="1.4"
      opacity=".55"
    />
    <path d="M5 33h30" fill="none" stroke="#1f3b2f" stroke-width="2.4" stroke-linecap="round" />
    <text
      x="20"
      y="30"
      text-anchor="middle"
      font-family="Fraunces, Georgia, serif"
      font-size="13"
      font-weight="700"
      fill="#1f3b2f"
      stroke="none"
    >
      B
    </text>
  </svg>
</template>

<style scoped>
.brand-mark {
  width: 36px;
  height: 36px;
  flex: none;
}
</style>
