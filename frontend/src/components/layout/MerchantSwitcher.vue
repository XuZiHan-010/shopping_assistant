<script setup lang="ts">
import { ChevronDown } from '@lucide/vue'
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{
  modelValue: string
  merchants: readonly string[]
}>()

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
</script>

<template>
  <div ref="rootElement" class="merchant-switcher">
    <button
      ref="triggerElement"
      class="merchant-switcher__trigger"
      type="button"
      aria-label="切换当前演示商家"
      :aria-expanded="isOpen"
      aria-controls="merchant-switcher-options"
      @click="isOpen = !isOpen"
    >
      <span class="merchant-switcher__status" aria-hidden="true"></span>
      <span class="merchant-switcher__name">{{ modelValue }}</span>
      <ChevronDown aria-hidden="true" :size="15" />
    </button>

    <ul v-if="isOpen" id="merchant-switcher-options" class="merchant-switcher__menu">
      <li v-for="merchant in props.merchants" :key="merchant">
        <button
          class="merchant-switcher__option"
          type="button"
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
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
  transition: var(--transition-interactive);
}

.merchant-switcher__trigger:hover {
  border-color: #cdd7fd;
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.merchant-switcher__status {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--color-teal);
  box-shadow: 0 0 0 3px rgba(24, 169, 153, 0.13);
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
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: #fff;
  box-shadow: 0 14px 32px rgba(37, 52, 82, 0.16);
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
  color: var(--color-text-secondary);
  background: transparent;
  font-size: var(--font-size-body);
  text-align: left;
}

.merchant-switcher__option:hover,
.merchant-switcher__option[aria-current='true'] {
  color: var(--color-primary-strong);
  background: var(--color-primary-soft);
}
</style>
