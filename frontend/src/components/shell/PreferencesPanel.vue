<script lang="ts">
// 模块级计数器生成 id：同页出现多个面板实例时 label/for 也不会串。
let instanceCount = 0
</script>

<script setup lang="ts">
/**
 * 偏好设置面板（左下角账号区打开，设计说明 §2.1、§3.2）：
 * - 主题：跟随系统 / 浅色 / 深色 → `<html data-theme>`；
 * - 语言：沿用 `stores/locale.ts`；
 * - 界面字号：小 / 标准 / 大 → `<html data-size>`；
 * - 助手快捷键说明（按键本身由 Task 6 的助手栏接线）。
 * 开合由父组件控制；本组件只在 Escape 或关闭按钮时发出 `close`。
 * 挂载（即打开）时把焦点移到第一项设置，键盘用户不必再从触发按钮 Tab 过来。
 * Escape 会 `preventDefault()`：外层（例如窄屏侧栏抽屉）据此只关面板、不连带关闭自己。
 */
import { X } from '@lucide/vue'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { SupportedLocale } from '@/i18n'
import { SUPPORTED_LOCALES } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'
import {
  SIZE_OPTIONS,
  THEME_OPTIONS,
  usePreferencesStore,
  type SizePreference,
  type ThemePreference,
} from '@/stores/preferences'
import { isApplePlatform } from '@/utils/platform'

const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const prefs = usePreferencesStore()
const localeStore = useLocaleStore()

instanceCount += 1
const titleId = `preferences-title-${instanceCount}`
const modifierKey = isApplePlatform() ? '⌘' : 'Ctrl'

const THEME_LABEL_KEYS = {
  system: 'preferences.themeSystem',
  light: 'preferences.themeLight',
  dark: 'preferences.themeDark',
} as const satisfies Record<ThemePreference, string>

const SIZE_LABEL_KEYS = {
  sm: 'preferences.sizeSm',
  md: 'preferences.sizeMd',
  lg: 'preferences.sizeLg',
} as const satisfies Record<SizePreference, string>

const LOCALE_LABEL_KEYS = {
  'zh-CN': 'preferences.languageZh',
  'en-US': 'preferences.languageEn',
} as const satisfies Record<SupportedLocale, string>

function onTheme(event: Event): void {
  const value = (event.target as HTMLSelectElement).value as ThemePreference
  if (THEME_OPTIONS.includes(value)) prefs.setTheme(value)
}

function onSize(event: Event): void {
  const value = (event.target as HTMLSelectElement).value as SizePreference
  if (SIZE_OPTIONS.includes(value)) prefs.setSize(value)
}

function onLocale(event: Event): void {
  const value = (event.target as HTMLSelectElement).value as SupportedLocale
  if (SUPPORTED_LOCALES.includes(value)) localeStore.setLocale(value)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.preventDefault()
  emit('close')
}

const dialogElement = ref<HTMLDivElement | null>(null)

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  const first = dialogElement.value?.querySelector<HTMLElement>('select')
  ;(first ?? dialogElement.value)?.focus()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div ref="dialogElement" class="prefs" role="dialog" tabindex="-1" :aria-labelledby="titleId">
    <div class="prefs__head">
      <h2 :id="titleId">{{ t('preferences.title') }}</h2>
      <button
        class="prefs__close"
        type="button"
        data-testid="preferences-close"
        :aria-label="t('preferences.close')"
        @click="emit('close')"
      >
        <X :size="18" aria-hidden="true" />
      </button>
    </div>

    <div class="pref">
      <div class="pref__text">
        <strong>{{ t('preferences.theme') }}</strong>
        <span>{{ t('preferences.themeHint') }}</span>
      </div>
      <label class="sr-only" :for="`${titleId}-theme`">{{ t('preferences.theme') }}</label>
      <select
        :id="`${titleId}-theme`"
        name="theme"
        autocomplete="off"
        :value="prefs.theme"
        @change="onTheme"
      >
        <option v-for="option in THEME_OPTIONS" :key="option" :value="option">
          {{ t(THEME_LABEL_KEYS[option]) }}
        </option>
      </select>
    </div>

    <div class="pref">
      <div class="pref__text">
        <strong>{{ t('preferences.language') }}</strong>
        <span>{{ t('preferences.languageHint') }}</span>
      </div>
      <label class="sr-only" :for="`${titleId}-language`">{{ t('preferences.language') }}</label>
      <select
        :id="`${titleId}-language`"
        name="language"
        autocomplete="off"
        :value="localeStore.locale"
        @change="onLocale"
      >
        <option
          v-for="option in SUPPORTED_LOCALES"
          :key="option"
          :value="option"
          :lang="option"
          translate="no"
        >
          {{ t(LOCALE_LABEL_KEYS[option]) }}
        </option>
      </select>
    </div>

    <div class="pref">
      <div class="pref__text">
        <strong>{{ t('preferences.size') }}</strong>
        <span>{{ t('preferences.sizeHint') }}</span>
      </div>
      <label class="sr-only" :for="`${titleId}-size`">{{ t('preferences.size') }}</label>
      <select
        :id="`${titleId}-size`"
        name="size"
        autocomplete="off"
        :value="prefs.size"
        @change="onSize"
      >
        <option v-for="option in SIZE_OPTIONS" :key="option" :value="option">
          {{ t(SIZE_LABEL_KEYS[option]) }}
        </option>
      </select>
    </div>

    <div class="pref">
      <div class="pref__text">
        <strong>{{ t('preferences.shortcut') }}</strong>
        <span>{{ t('preferences.shortcutHint') }}</span>
      </div>
      <span class="pref__keys"
        ><kbd>{{ modifierKey }}</kbd> <kbd>J</kbd></span
      >
    </div>
  </div>
</template>

<style scoped>
.prefs {
  width: 340px;
  max-width: calc(100vw - 24px);
  border: 1px solid var(--line);
  border-radius: 12px;
  color: var(--ink);
  background: var(--raised);
  box-shadow: var(--shadow-lg);
}

.prefs__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 12px 10px 16px;
  border-bottom: 1px solid var(--line);
}

.prefs__head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-2);
}

.prefs__close {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--ink-soft);
  background: none;
  transition:
    background-color 150ms,
    color 150ms;
}

.prefs__close:hover {
  color: var(--ink);
  background: var(--hover);
}

.pref {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--line);
}

.pref:last-child {
  border-bottom: 0;
}

.pref__text {
  min-width: 0;
}

.pref__text > strong {
  display: block;
  font-size: 13.5px;
  font-weight: 600;
}

.pref__text > span {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-soft);
}

.pref select {
  height: 32px;
  flex: none;
  padding: 0 28px 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  color: var(--ink);
  background-color: var(--card);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca49f' stroke-width='2.2' stroke-linecap='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 9px center;
  font-size: 13px;
  appearance: none;
}

.pref select:hover {
  border-color: var(--ink-faint);
}

.pref__keys {
  flex: none;
  white-space: nowrap;
}

kbd {
  display: inline-flex;
  align-items: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border: 1px solid var(--line-strong);
  border-bottom-width: 2px;
  border-radius: 6px;
  background: var(--card);
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--ink-2);
}
</style>
