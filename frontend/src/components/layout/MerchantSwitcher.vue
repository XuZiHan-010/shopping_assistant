<script setup lang="ts">
import { ChevronDown, ChevronsUpDown } from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { i18n } from '@/i18n'

// 直接读全局 `i18n` 单例而不是 `useI18n()`：与 `ConversationDrawer.vue`
// 同一个理由，见那边的注释。
const triggerAria = computed(() => i18n.global.t('merchantSwitcher.triggerAria'))
const listAria = computed(() => i18n.global.t('merchantSwitcher.listAria'))

const props = withDefaults(
  defineProps<{
    modelValue: string
    merchants: readonly string[]
    /**
     * `side`：商家工作台侧栏品牌区的样式（W Task 5），深底浅字、菜单向下展开；
     * 行为与默认样式完全相同。
     */
    variant?: 'default' | 'side'
    /** 仅 `side` 样式显示的第二行说明，例如「演示商家」。 */
    caption?: string
  }>(),
  { variant: 'default', caption: '' },
)

const emit = defineEmits<{
  'update:modelValue': [merchant: string]
}>()

const isOpen = ref(false)
const rootElement = ref<HTMLDivElement | null>(null)
const triggerElement = ref<HTMLButtonElement | null>(null)

function closeMenu(returnFocus = false): void {
  isOpen.value = false
  if (returnFocus) triggerElement.value?.focus()
}

function handleDocumentPointerdown(event: PointerEvent): void {
  if (!(event.target instanceof Node) || rootElement.value?.contains(event.target)) return
  closeMenu()
}

function handleDocumentKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !isOpen.value) return
  event.preventDefault()
  closeMenu(true)
}

function removeDocumentListeners(): void {
  document.removeEventListener('pointerdown', handleDocumentPointerdown)
  document.removeEventListener('keydown', handleDocumentKeydown)
}

watch(isOpen, (open) => {
  removeDocumentListeners()
  if (!open) return

  document.addEventListener('pointerdown', handleDocumentPointerdown)
  document.addEventListener('keydown', handleDocumentKeydown)
})

onBeforeUnmount(removeDocumentListeners)

function chooseMerchant(merchant: string): void {
  emit('update:modelValue', merchant)
  closeMenu(true)
}

/**
 * 供外部（`AssistantView`，F3 Task 6）在演示身份失效时强制打开切换器并把焦点
 * 交给触发按钮——这是 401 恢复流程的一部分：菜单内部平时只由用户点击触发按钮
 * 自己控制开合，这里是唯一的外部入口。
 */
function openAndFocus(): void {
  isOpen.value = true
  triggerElement.value?.focus()
}

defineExpose({ openAndFocus })
</script>

<template>
  <div
    ref="rootElement"
    class="merchant-switcher"
    :class="{ 'merchant-switcher--side': props.variant === 'side' }"
  >
    <button
      ref="triggerElement"
      class="merchant-switcher__trigger"
      type="button"
      data-testid="merchant-switcher"
      :aria-label="triggerAria"
      :aria-expanded="isOpen"
      aria-controls="merchant-switcher-options"
      @click="isOpen = !isOpen"
    >
      <template v-if="props.variant === 'side'">
        <span class="merchant-switcher__text">
          <strong class="merchant-switcher__name" translate="no">{{ modelValue }}</strong>
          <span v-if="props.caption" class="merchant-switcher__caption">{{ props.caption }}</span>
        </span>
        <ChevronsUpDown aria-hidden="true" :size="16" class="merchant-switcher__chev" />
      </template>
      <template v-else>
        <span class="merchant-switcher__status" aria-hidden="true"></span>
        <span class="merchant-switcher__name">{{ modelValue }}</span>
        <ChevronDown aria-hidden="true" :size="15" />
      </template>
    </button>

    <!-- listbox / option：触发按钮已经声明了 aria-expanded 与 aria-controls，
         弹出的列表若没有角色，读屏只会念成一个普通列表，读不出「共几项、当前
         第几项、已选中哪一项」。li 让出角色，由内部按钮承担 option。 -->
    <ul
      v-if="isOpen"
      id="merchant-switcher-options"
      class="merchant-switcher__menu"
      role="listbox"
      :aria-label="listAria"
    >
      <li v-for="merchant in props.merchants" :key="merchant" role="presentation">
        <button
          class="merchant-switcher__option"
          type="button"
          role="option"
          :aria-selected="merchant === modelValue"
          :aria-current="merchant === modelValue ? 'true' : undefined"
          :data-merchant="merchant"
          @click="chooseMerchant(merchant)"
        >
          <span class="merchant-switcher__status" aria-hidden="true"></span>
          {{ merchant }}
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.merchant-switcher {
  position: relative;
  min-width: 0;
}

.merchant-switcher__trigger {
  width: 100%;
  min-width: 0;
  height: var(--control-height);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2-5);
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  color: var(--ink-2);
  background: var(--card);
  box-shadow: var(--shadow-sm);
  transition: var(--transition-interactive);
}

.merchant-switcher__trigger:hover {
  border-color: var(--line-strong);
  color: var(--accent);
  background: var(--accent-soft);
}

.merchant-switcher__status {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-soft);
}

.merchant-switcher__name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.merchant-switcher__menu {
  position: absolute;
  top: calc(100% + var(--space-2));
  right: 0;
  z-index: 20;
  width: max-content;
  min-width: 100%;
  max-width: min(260px, calc(100vw - 14px));
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: var(--space-1);
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--raised);
  box-shadow: var(--shadow-lg);
  list-style: none;
}

.merchant-switcher__menu li {
  min-width: 0;
}

.merchant-switcher__option {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-2-5);
  border-radius: 8px;
  color: var(--ink-2);
  background: transparent;
  font-size: var(--font-size-body);
  text-align: left;
}

.merchant-switcher__option:hover,
.merchant-switcher__option[aria-current='true'] {
  color: var(--accent-strong);
  background: var(--accent-soft);
}

/* ---------- 侧栏品牌区样式（定稿原型 `.brand`） ---------- */
.merchant-switcher--side .merchant-switcher__trigger {
  height: auto;
  gap: 11px;
  padding: 6px 8px;
  border: 1px solid var(--side-line);
  border-radius: 12px;
  color: var(--side-ink);
  background: rgba(255, 255, 255, 0.04);
  box-shadow: none;
}

.merchant-switcher--side .merchant-switcher__trigger:hover {
  border-color: rgba(239, 233, 220, 0.24);
  color: var(--side-ink);
  background: var(--side-hover);
}

.merchant-switcher__text {
  min-width: 0;
  flex: 1;
  text-align: left;
}

.merchant-switcher--side .merchant-switcher__name {
  display: block;
  font-size: 14px;
  font-weight: 650;
}

.merchant-switcher__caption {
  display: block;
  overflow: hidden;
  font-size: 12px;
  color: var(--side-soft);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.merchant-switcher__chev {
  flex: none;
  color: var(--side-faint);
}

.merchant-switcher--side .merchant-switcher__menu {
  left: 0;
  right: 0;
  top: calc(100% + 4px);
  width: auto;
  max-width: none;
  padding: 6px;
  border-radius: 12px;
  background: var(--raised);
  box-shadow: var(--shadow-lg);
}

.merchant-switcher--side .merchant-switcher__option {
  padding: 7px 8px;
  color: var(--ink);
  font-size: 13.5px;
}

.merchant-switcher--side .merchant-switcher__option:hover {
  color: var(--ink);
  background: var(--hover);
}

.merchant-switcher--side .merchant-switcher__option[aria-current='true'] {
  color: var(--accent-ink);
  background: var(--accent-soft);
}
</style>
