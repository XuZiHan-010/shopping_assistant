<script setup lang="ts">
import { useAppError } from '@/composables/useAppError'

// 全局外壳只承载路由出口和一个全局错误区域。
const { message, clearError } = useAppError()
</script>

<template>
  <!-- role="status" + aria-live 让读屏用户也能感知错误，不只是视觉提示。 -->
  <div v-if="message" class="app-error" role="status" aria-live="polite">
    <span>{{ message }}</span>
    <button type="button" @click="clearError">关闭</button>
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
