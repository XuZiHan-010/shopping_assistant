import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useOpsChatStore } from './opsChat'
import { isRailShortcut, useRailStore } from './rail'

function key(init: KeyboardEventInit): KeyboardEvent {
  return new KeyboardEvent('keydown', { cancelable: true, ...init })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('助手栏开合 store', () => {
  it('默认收起，历史面板也收起', () => {
    const rail = useRailStore()

    expect(rail.open).toBe(false)
    expect(rail.historyOpen).toBe(false)
  })

  it('show / hide / toggle 切换开合', () => {
    const rail = useRailStore()

    rail.toggle()
    expect(rail.open).toBe(true)
    rail.toggle()
    expect(rail.open).toBe(false)
    rail.show()
    expect(rail.open).toBe(true)
    rail.hide()
    expect(rail.open).toBe(false)
  })

  it('ask() 经 opsChat.prefill() 预填、回到对话面板并打开助手栏，不发送', () => {
    const rail = useRailStore()
    const chat = useOpsChatStore()
    rail.toggleHistory()
    expect(rail.historyOpen).toBe(true)

    rail.ask('给「测试商品」起草补货草稿')

    expect(chat.pendingInput).toBe('给「测试商品」起草补货草稿')
    expect(rail.open).toBe(true)
    expect(rail.historyOpen).toBe(false)
    expect(chat.busy).toBe(false)
    expect(chat.messages).toEqual([])
  })

  it('openConversation() 打开助手栏并记下要打开的对话，只交出一次', () => {
    const rail = useRailStore()

    rail.openConversation('c-1')

    expect(rail.open).toBe(true)
    expect(rail.historyOpen).toBe(false)
    expect(rail.takePendingConversation()).toBe('c-1')
    expect(rail.takePendingConversation()).toBeNull()
  })

  it('换商家（会话态重置）不关闭助手栏', () => {
    const rail = useRailStore()
    rail.show()

    // opsChat 注册的会话态重置只清对话，不动开合状态。
    useOpsChatStore().startNew()

    expect(rail.open).toBe(true)
  })
})

describe('Ctrl/⌘ + J 快捷键判定', () => {
  it('Ctrl + J 与 ⌘ + J 都算，大小写不敏感', () => {
    expect(isRailShortcut(key({ key: 'j', ctrlKey: true }))).toBe(true)
    expect(isRailShortcut(key({ key: 'J', ctrlKey: true }))).toBe(true)
    expect(isRailShortcut(key({ key: 'j', metaKey: true }))).toBe(true)
  })

  it('不带修饰键、带 Alt 或 Shift（Chrome 的 Ctrl+Shift+J 是开发者工具）都不算', () => {
    expect(isRailShortcut(key({ key: 'j' }))).toBe(false)
    expect(isRailShortcut(key({ key: 'j', ctrlKey: true, altKey: true }))).toBe(false)
    expect(isRailShortcut(key({ key: 'J', ctrlKey: true, shiftKey: true }))).toBe(false)
    expect(isRailShortcut(key({ key: 'k', ctrlKey: true }))).toBe(false)
  })

  it('输入法组字过程中不算', () => {
    expect(isRailShortcut(key({ key: 'j', ctrlKey: true, isComposing: true }))).toBe(false)
  })
})
