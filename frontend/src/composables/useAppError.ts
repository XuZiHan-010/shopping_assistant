import { readonly, ref } from 'vue'

/**
 * 最小全局错误状态。
 *
 * 本模块只负责持有「一条已经翻译好的错误文案」并由 `App.vue` 的无障碍状态
 * 区域呈现；它本身不关心当前是中文还是英文——调用方（`describeError()` /
 * `i18n.global.t()`）在调用 `showError()` 之前就已经按当前语言把文案翻译好，
 * 这里存的只是最终展示字符串，不做二次翻译。
 *
 * 模块级单例：全局提示需要跨组件共享同一份状态，不依赖任何一个 Store。
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
