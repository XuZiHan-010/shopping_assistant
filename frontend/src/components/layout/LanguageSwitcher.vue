<script setup lang="ts">
import { Languages } from '@lucide/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { SupportedLocale } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

const localeStore = useLocaleStore()
const { t } = useI18n()

// 按钮永远显示「切到哪个语言」，而不是「当前是哪个语言」——文案和
// aria-label 都用当前显示语言书写目标语言的名字，绝不把两种语言的字样
// 混在同一个按钮里。
const targetLocale = computed<SupportedLocale>(() =>
  localeStore.locale === 'zh-CN' ? 'en-US' : 'zh-CN',
)

const label = computed(() =>
  targetLocale.value === 'en-US' ? t('languageSwitcher.english') : t('languageSwitcher.chinese'),
)

const ariaLabel = computed(() =>
  targetLocale.value === 'en-US'
    ? t('languageSwitcher.switchToEnglish')
    : t('languageSwitcher.switchToChinese'),
)

function toggle(): void {
  localeStore.setLocale(targetLocale.value)
}
</script>

<template>
  <button
    type="button"
    class="language-switcher"
    data-testid="language-switcher"
    :aria-label="ariaLabel"
    :title="ariaLabel"
    @click="toggle"
  >
    <Languages :size="18" aria-hidden="true" />
    <span class="language-switcher__label">{{ label }}</span>
  </button>
</template>

<style scoped>
/* 复刻现有顶栏图标按钮视觉族（AssistantView 的 `.header-icon-button` /
   `.new-chat-button`，OpsDashboardView、KnowledgeBaseView 的对应按钮）。
   三个页头各自的类名不共享作用域，因此这里用同一批全局设计 Token
   （`assets/tokens.css`）独立复刻一份，而不是依赖父组件的类名。 */
.language-switcher {
  height: var(--control-height);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
  white-space: nowrap;
  transition: var(--transition-interactive);
}

.language-switcher:hover {
  border-color: #cdd7fd;
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.language-switcher:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

@media (max-width: 560px) {
  .language-switcher {
    width: 36px;
    padding: 0;
    justify-content: center;
  }

  .language-switcher__label {
    display: none;
  }
}
</style>
