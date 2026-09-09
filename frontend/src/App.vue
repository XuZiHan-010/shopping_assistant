<script setup lang="ts">
import { computed, watch } from 'vue'

import { useAppError } from '@/composables/useAppError'
import { i18n, type SupportedLocale } from '@/i18n'

// 全局外壳只承载路由出口、一个全局错误区域，以及跟随语言切换的品牌 favicon。
const { message, clearError } = useAppError()

/**
 * 直接读全局 `i18n` 单例而不是 `useI18n()`：后者要求 i18n 插件已通过
 * `app.use(i18n)` 安装到当前组件树，router/index.spec.ts 等既有测试用最小
 * 插件集合挂载 `App`，不想因为这里改用 Composable 就被迫处处补插件。
 * `stores/locale.ts` 已经是同样的直接读写单例的用法。
 */
const closeLabel = computed(() => i18n.global.t('appError.close'))

/**
 * favicon 用静态资源文件切换，不是内联 SVG——`<link rel="icon">`
 * 本身不解析 SVG 内部的可访问树，只是把文件当图标资源加载，因此只需要按
 * 语言换一下引用的文件路径。真正需要在可访问树里暴露正确语言 `<title>`
 * 的场景（比如把 Logo 当内联 SVG 展示）由具体使用它的页面在挂载时选择
 * 对应资源文件，见 `public/borough-logo.svg` / `public/borough-logo-en.svg`。
 */
const LOGO_BY_LOCALE: Record<SupportedLocale, string> = {
  'zh-CN': '/borough-logo.svg',
  'en-US': '/borough-logo-en.svg',
}

function syncFavicon(locale: SupportedLocale): void {
  const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (link) link.href = LOGO_BY_LOCALE[locale]
}

watch(i18n.global.locale, syncFavicon, { immediate: true })
</script>

<template>
  <!-- role="status" + aria-live 让读屏用户也能感知错误，不只是视觉提示。 -->
  <div v-if="message" class="app-error" role="status" aria-live="polite">
    <span>{{ message }}</span>
    <button type="button" @click="clearError">{{ closeLabel }}</button>
  </div>

  <RouterView />
</template>

<style scoped>
.app-error {
  position: fixed;
  top: var(--space-3);
  right: var(--space-3);
  z-index: 50;
  display: flex;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border: 1px solid #f4c7c1;
  border-radius: var(--radius-control);
  background: var(--color-danger-surface);
  color: var(--color-danger-text);
  box-shadow: var(--shadow-control);
}
</style>
