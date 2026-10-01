import { ref } from 'vue'
import { defineStore } from 'pinia'

import { useOpsChatStore } from './opsChat'

/**
 * 助手栏开合（W Task 6，设计说明 §2.1、§3.2）。
 *
 * - 默认收起；侧栏「运营助手」、顶栏按钮、`Ctrl/⌘ + J` 切换，Esc 收起（键盘由外壳接线）；
 * - 页面上任意「问助手」调用 `ask()`：经 `opsChat.prefill()` 预填并打开助手栏，**只填不发**（D18④）；
 * - 「历史」面板的开合也放在这里：`ask()` 与打开指定对话都要切回对话面板。
 *
 * 开合是纯界面状态，不随换商家重置（会话与目录由 `opsChat` 的会话态重置负责清空）。
 */
export const useRailStore = defineStore('rail', () => {
  const open = ref(false)
  const historyOpen = ref(false)
  /** `/?assistant=open&conversation=…` 要打开的对话；助手栏拿到可用会话后取走一次。 */
  const pendingConversationId = ref<string | null>(null)

  function show(): void {
    open.value = true
  }

  function hide(): void {
    open.value = false
  }

  function toggle(): void {
    open.value = !open.value
  }

  function toggleHistory(): void {
    historyOpen.value = !historyOpen.value
  }

  function showChat(): void {
    historyOpen.value = false
  }

  /** 页面上的「问助手」：预填问题并打开助手栏，不代为发送。 */
  function ask(text: string): void {
    useOpsChatStore().prefill(text)
    historyOpen.value = false
    open.value = true
  }

  function openConversation(id: string): void {
    pendingConversationId.value = id
    historyOpen.value = false
    open.value = true
  }

  function takePendingConversation(): string | null {
    const id = pendingConversationId.value
    pendingConversationId.value = null
    return id
  }

  return {
    open,
    historyOpen,
    pendingConversationId,
    show,
    hide,
    toggle,
    toggleHistory,
    showChat,
    ask,
    openConversation,
    takePendingConversation,
  }
})

/**
 * `Ctrl + J`（Windows / Linux）或 `⌘ + J`（macOS）。Alt、Shift 组合不算——
 * Chrome 的 `Ctrl + Shift + J` 是开发者工具；输入法组字过程中也不算。
 */
export function isRailShortcut(event: KeyboardEvent): boolean {
  if (event.isComposing) return false
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return false
  return event.key.toLowerCase() === 'j'
}
