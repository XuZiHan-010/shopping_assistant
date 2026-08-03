import { ref } from 'vue'
import { defineStore } from 'pinia'

/**
 * F1 只需要在切换演示商家或新建会话时回到空状态。
 * F2 会在同一 Store 中接入 Mock 会话与消息，切勿在此提前构造其完整形态。
 */
export const useChatStore = defineStore('chat', () => {
  const isEmptyConversation = ref(true)

  function reset(): void {
    isEmptyConversation.value = true
  }

  return { isEmptyConversation, reset }
})
