import { readonly, ref } from 'vue'

/**
 * 最小全局错误状态。
 *
 * F0 只提供「显示一条可读的中文错误」这一件事，由 `App.vue` 的无障碍状态区域
 * 呈现。完整的按 `code` 分支渲染（前端方案 §10）属于 F3，届时在此基础上扩展。
 *
 * 模块级单例：F0 还没有 Store，全局提示需要跨组件共享同一份状态。
 */
const message = ref<string | null>(null)

export function useAppError() {
  return {
    message: readonly(message),
    showError(text: string) {
      message.value = text
    },
    clearError() {
      message.value = null
    },
  }
}
