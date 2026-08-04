import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { useChatStore } from '@/stores/chat'

import ConversationDrawer from './ConversationDrawer.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
})

describe('ConversationDrawer', () => {
  it('列出已有会话，删除需要二次确认', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    expect(wrapper.findAll('[data-testid="conversation-item"]')).toHaveLength(1)

    await wrapper.get('[data-testid="conversation-delete"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    // 第一次点击只进入确认态，会话不能就这么没了——删除无法撤销。
    expect(store.conversations).toHaveLength(1)

    await wrapper.get('[data-testid="conversation-delete-confirm"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.conversations).toHaveLength(0)
  })

  it('确认前可以取消，会话保留', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    await wrapper.get('[data-testid="conversation-delete"]').trigger('click')
    await wrapper.get('[data-testid="conversation-delete-cancel"]').trigger('click')

    expect(store.conversations).toHaveLength(1)
    expect(wrapper.find('[data-testid="conversation-delete-confirm"]').exists()).toBe(false)
  })

  it('删除失败时给出可见提示，而不是留一条未处理的 Promise 拒绝', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    setChatTransport(async () => {
      throw new Error('网络中断')
    })

    await wrapper.get('[data-testid="conversation-delete"]').trigger('click')
    await wrapper.get('[data-testid="conversation-delete-confirm"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('删除失败')
    expect(store.conversations).toHaveLength(1)
  })

  it('点击会话把历史消息载入当前会话', async () => {
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    await store.loadConversations()
    const conversationId = store.conversations[0].id
    store.reset()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    await wrapper.get('[data-testid="conversation-open"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.sessionId).toBe(conversationId)
    expect(store.messages).toHaveLength(2)
    expect(store.messages[0].text).toBe('昨天总 GMV 是多少？')
    expect(store.messages[0].status).toBe('complete')
  })

  it('open 为 false 时不渲染内容', () => {
    const wrapper = mount(ConversationDrawer, { props: { open: false } })

    expect(wrapper.find('[data-testid="conversation-item"]').exists()).toBe(false)
  })

  it('Escape 关闭抽屉', async () => {
    const wrapper = mount(ConversationDrawer, { props: { open: true } })

    await wrapper.get('[data-testid="drawer-panel"]').trigger('keydown', { key: 'Escape' })

    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
